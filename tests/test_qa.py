import json
from tiktok_director.qa import write_job_report
from director.quality_control import write_quality_report

def test_report_written(tmp_path):
    path=write_job_report(tmp_path,"partial_success","planning only",[{"name":"planning","status":"success"}])
    data=json.loads(path.read_text())
    assert data["status"] == "partial_success"
    assert (tmp_path/"quality_report.md").exists()

def test_quality_report_rejects_unknown_status(tmp_path):
    try:
        write_quality_report(tmp_path, "unknown", "test")
        assert False, "Expected ValueError"
    except ValueError:
        pass
