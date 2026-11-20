"""The cross-host barriers of pipeline/, under strategy: free, on localhost."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PIPE = ROOT / "ansible" / "pipeline"


def test_waiters_proceed_on_ready_and_fail_fast_on_failure(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    play = tmp_path / "p.yml"
    play.write_text(f"""
- hosts: dc,mem,bad,late
  gather_facts: false
  strategy: free
  vars: {{lab_run_dir: "{run}", lab_wait_timeout: 60}}
  tasks:
    - block:
        - {{command: sleep 3, when: inventory_hostname == 'dc'}}
        - {{fail: {{msg: boom}}, when: inventory_hostname == 'bad'}}
        - include_tasks: {PIPE}/mark.yml
          vars: {{lab_stage: dc_ready}}
          when: inventory_hostname in ['dc', 'bad']
        - include_tasks: {PIPE}/wait.yml
          vars: {{lab_stage: dc_ready, lab_wait_hosts: [dc]}}
          when: inventory_hostname == 'mem'
        - include_tasks: {PIPE}/wait.yml
          vars: {{lab_stage: dc_ready, lab_wait_hosts: [bad]}}
          when: inventory_hostname == 'late'
      rescue:
        - include_tasks: {PIPE}/mark.yml
          vars: {{lab_stage: dc_ready, lab_stage_state: failed}}
        - fail: {{msg: failed}}
""")
    bin_ = Path(sys.executable).with_name("ansible-playbook")
    p = subprocess.run([str(bin_), "-i", "dc,mem,bad,late,", "-c", "local", str(play)],
                       capture_output=True, text=True, timeout=120,
                       env={**os.environ, "ANSIBLE_NOCOLOR": "1"})
    recap = p.stdout[p.stdout.index("PLAY RECAP"):]
    line = {ln.split()[0]: ln for ln in recap.splitlines()[1:] if ln.strip()}
    assert "failed=0" in line["dc"] and "failed=0" in line["mem"]
    assert "failed=1" in line["bad"] and "failed=1" in line["late"]
    assert (run / "dc.dc_ready").read_text().strip() == "ready"
    assert (run / "bad.dc_ready").read_text().strip() == "failed"
