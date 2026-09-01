"""Test-only external profile proving the plugin-to-QEMU extension path."""
from pathlib import Path

from driver_profiles import MatchResult, ProfilePlan


REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_TEMPLATE = REPO_ROOT / "benchmarks" / "experiments" / "edu.json"


class TestPciProfile:
    profile_id = "test-pci-plugin"
    bus = "pci"

    def evidence_from_source(self, source_text):
        if "struct pci_driver" not in source_text:
            return {}
        return {
            "bus": self.bus,
            "bindings": {"pci_driver.probe": "plugin-evidence"},
            "resources": {"pci_device": {"source": True}},
        }

    def match(self, evidence):
        if evidence.get("bus") != self.bus:
            return None
        return MatchResult(
            self.profile_id, self.bus, "external PCI plugin evidence", 100)

    def plan(self, evidence):
        return ProfilePlan(
            profile_id=self.profile_id,
            bus=self.bus,
            required_capabilities=("registration", "probe", "unload"),
            optional_capabilities=("subsystem",),
            runtime_adapter="qemu-profile",
            fixture={"kind": "qemu-pci", "config": {}},
            manifest_template=str(MANIFEST_TEMPLATE),
            runtime_overrides={"qemu": {"module": "edu_drv"}},
        )


def register_profiles(registry):
    registry.register(TestPciProfile())
