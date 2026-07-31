import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from plugins.teleinformation.teleinformation_frame_store import (
    TeleinformationFrameStore,
)
from plugins.teleinformation.teleinformation_ingestion import (
    TeleinformationIngestionHTTPServer,
)


def post(url: str, token: str) -> int:
    request = Request(
        url,
        data=json.dumps(
            {
                "schema_version": 1,
                "source": "rpi-linky",
                "meter_id": "041964385922",
                "frame": {
                    "SINSTS": {"value": 1392},
                    "NTARF": {"value": 2},
                    "EASF02": {"value": 6931422},
                },
            }
        ).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=2) as response:
        return response.status


def test_ingestion_server_authenticates_and_stores_frame() -> None:
    store = TeleinformationFrameStore()
    server = TeleinformationIngestionHTTPServer(
        frame_store=store,
        token="secret",
        host="127.0.0.1",
        port=0,
    )
    server.start()
    try:
        assert server.address is not None
        url = f"http://127.0.0.1:{server.address[1]}/v1/teleinformation/frames"
        assert post(url, "secret") == 202
        frame = store.get(source="rpi-linky", meter_id="041964385922")
        assert frame is not None
        assert frame.values["SINSTS"] == 1392

        with pytest.raises(HTTPError) as error:
            post(url, "wrong")
        assert error.value.code == 401
    finally:
        server.stop()
