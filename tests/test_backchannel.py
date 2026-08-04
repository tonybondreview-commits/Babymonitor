"""Test del backchannel (parsing SDP), senza camera reale."""

from babymonitor.backchannel import Backchannel


def _bc():
    return Backchannel("rtsp://admin:admin123@192.168.1.67:554/onvif1")


def test_pick_backchannel_pcmu_absolute_control():
    sdp = (
        "v=0\r\n"
        "m=audio 0 RTP/AVP 0\r\n"
        "a=rtpmap:0 PCMU/8000\r\n"
        "a=control:rtsp://192.168.1.67:554/onvif1/backchannel\r\n"
        "a=sendonly\r\n"
    )
    ctrl, pt, codec = _bc()._pick_backchannel(sdp)
    assert pt == 0
    assert codec == "mulaw"
    assert ctrl.endswith("/backchannel")


def test_pick_backchannel_pcma_relative_control():
    sdp = (
        "m=audio 0 RTP/AVP 8\r\n"
        "a=rtpmap:8 PCMA/8000\r\n"
        "a=control:trackID=2\r\n"
        "a=sendonly\r\n"
    )
    ctrl, pt, codec = _bc()._pick_backchannel(sdp)
    assert pt == 8
    assert codec == "alaw"
    assert ctrl == "rtsp://192.168.1.67:554/onvif1/trackID=2"


def test_pick_backchannel_none():
    ctrl, pt, codec = _bc()._pick_backchannel("v=0\r\nm=video 0 RTP/AVP 96\r\n")
    assert ctrl == "" and codec == ""


def test_parses_url():
    bc = _bc()
    assert bc.host == "192.168.1.67" and bc.port == 554
    assert bc.user == "admin" and bc.password == "admin123"
