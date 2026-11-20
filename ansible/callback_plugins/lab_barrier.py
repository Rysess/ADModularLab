"""Release hosts waiting on a host that went unreachable.

pipeline/windows.yml signals failures from a rescue block, but Ansible never
runs rescue for an unreachable host, so whoever waits on it would sit until the
barrier timeout. This callback runs in the controller process and writes the
'failed' markers for it instead. Enabled in ansible.cfg; a no-op unless ./lab
sets LAB_RUN_DIR.
"""
import os

from ansible.plugins.callback import CallbackBase

STAGES = ("dc_ready", "joined", "identity")


class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = "aggregate"
    CALLBACK_NAME = "lab_barrier"
    CALLBACK_NEEDS_ENABLED = True

    def _mark_failed(self, host):
        run_dir = os.environ.get("LAB_RUN_DIR")
        if not run_dir or not os.path.isdir(run_dir):
            return
        for stage in STAGES:
            path = os.path.join(run_dir, f"{host}.{stage}")
            if not os.path.exists(path):        # never overwrite a 'ready'
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write("failed\n")

    def v2_runner_on_unreachable(self, result):
        self._mark_failed(result._host.get_name())
