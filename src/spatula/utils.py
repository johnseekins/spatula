import dataclasses
from influxdb_client import InfluxDBClient
from influxdb_client.client.write_api import SYNCHRONOUS
from influxdb_client.client.write.point import Point
from influxdb_client.domain.write_precision import WritePrecision
from lxml.etree import _Element  # type: ignore
import logging
import os
import pprint
import time
import typing

# utilities for working with optional dependencies
try:
    from attr import has as attr_has
    from attr import fields as attr_fields
    from attr import asdict as attr_asdict
except ImportError:  # pragma: no cover
    attr_has = lambda x: False  # type: ignore # noqa
    attr_fields = lambda x: []  # type: ignore # noqa
    attr_asdict = lambda x: {}  # type: ignore # noqa


def _display_element(obj: _Element) -> str:
    elem_str = f"<{obj.tag} "

    # := if we drop 3.7
    id_str = obj.get("id")
    class_str = obj.get("class")

    if id_str:
        elem_str += f"id='{id_str}'"
    elif class_str:
        elem_str += f"class='{class_str}'"
    else:
        elem_str += " ".join(f"{k}='{v}'" for k, v in obj.attrib.items())

    return f"{elem_str.strip()}> @ line {obj.sourceline}"


def _is_pydantic(obj: typing.Any) -> bool:
    return hasattr(obj, "__fields__") and hasattr(obj, "dict")


def _display(obj: typing.Any) -> str:
    if isinstance(obj, _Element):
        return _display_element(obj)
    else:
        # if there's a dict representation, use that, otherwise str
        try:
            return pprint.pformat(_obj_to_dict(obj))
        except ValueError:
            return str(obj)


def _obj_to_dict(obj: typing.Any) -> typing.Optional[typing.Dict]:
    if obj is None or isinstance(obj, dict):
        return obj
    elif dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    elif attr_has(obj):
        return attr_asdict(obj)
    elif _is_pydantic(obj):
        return obj.dict()
    else:
        raise ValueError(f"invalid type: {obj} ({type(obj)})")


def write_influx_stats(
    metrics: list,
    org: typing.Optional[str] = "",
    url: typing.Optional[str] = "",
    token: typing.Optional[str] = "",
) -> None:
    """
    A metric is a list of objects that look like:
    {
      "metric": "votes",
      "tags": {
        "jurisdiction": "ca"
      },
      "fields": {
        "passed": 12,
        "vetoed": 1,
        "failed": 2,
        "collected": 15
      }
    }

    Our example turns into the following metrics:
    votes_passed{jurisdiction="ca"} == 12
    votes_vetoed{jurisdiction="ca"} == 1
    votes_failed{jurisdiction="ca"} == 2
    votes_collected{jurisdiction="ca"} == 15
    """
    if not url:
        try:
            url = os.environ.get("INFLUX_ENDPOINT")
        except Exception:
            raise ValueError("Missing configuration for stats output INFLUX_ENDPOINT")
    if not token:
        try:
            token = os.environ.get("INFLUX_TOKEN")
        except Exception:
            raise ValueError("Missing configuration for stats output INFLUX_TOKEN")
    ts = time.time()
    points = list()
    for m in metrics:
        p = Point(m["metric"])
        p.time(int(m.get("timestamp", ts)), WritePrecision.S)
        """
        use list comprehensions 'cause they're technically faster than for loops
        But this is simply turning a dictionary of k=v pairs into tags/fields
        in the point object
        """
        [p.tag(t, v) for t, v in m.get("tags", {}).items()]
        [p.field(f, v) for f, v in m["fields"].items()]
        points.append(p)
    try:
        client = InfluxDBClient(
            url=url,
            token=token,
            org=org,
            enable_gzip=True,
        )
        write_api = client.write_api(write_options=SYNCHRONOUS)
        write_api.write("", record=points)
    except Exception as e:
        logging.warning(f"Failed to write stats: {e}")
