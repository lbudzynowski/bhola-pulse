from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest

from src.bhola_collectors import (
    CpuTimes,
    SystemCollectors,
    cpu_percent,
    read_cpu_times,
    read_disk_counters,
    read_memory_percent,
    read_temperatures,
)


class CollectorTests(unittest.TestCase):
    def test_cpu_and_memory_read_proc_without_identifiers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            (proc / "stat").write_text("cpu  100 10 40 800 50 0 0 0\n", encoding="utf-8")
            (proc / "meminfo").write_text(
                "MemTotal: 1000 kB\nMemAvailable: 250 kB\n",
                encoding="utf-8",
            )
            self.assertEqual(read_cpu_times(proc), CpuTimes(idle=850, total=1000))
            self.assertEqual(read_memory_percent(proc), 75.0)
        self.assertAlmostEqual(cpu_percent(CpuTimes(850, 1000), CpuTimes(930, 1100)), 20.0)

    def test_temperature_categories_and_missing_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sys_root = Path(directory)
            cpu = sys_root / "class/hwmon/hwmon0"
            gpu = sys_root / "class/hwmon/hwmon1"
            nvme = sys_root / "class/hwmon/hwmon2"
            for path in (cpu, gpu, nvme):
                path.mkdir(parents=True)
            (cpu / "name").write_text("k10temp\n", encoding="utf-8")
            (cpu / "temp1_input").write_text("71500\n", encoding="utf-8")
            (cpu / "temp1_label").write_text("Tctl\n", encoding="utf-8")
            (gpu / "name").write_text("amdgpu\n", encoding="utf-8")
            (gpu / "temp1_input").write_text("55000\n", encoding="utf-8")
            (gpu / "temp1_label").write_text("edge\n", encoding="utf-8")
            (nvme / "name").write_text("nvme\n", encoding="utf-8")
            (nvme / "temp1_input").write_text("48000\n", encoding="utf-8")
            (nvme / "temp1_label").write_text("Composite\n", encoding="utf-8")
            self.assertEqual(read_temperatures(sys_root), {"cpu": 71.5, "gpu": 55.0, "nvme": 48.0})

        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(
                read_temperatures(Path(directory)),
                {"cpu": None, "gpu": None, "nvme": None},
            )

    def test_disk_counters_skip_partitions_and_virtual_devices(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proc = root / "proc"
            sys_root = root / "sys"
            proc.mkdir()
            for name in ("nvme0n1", "nvme0n1p1", "loop0"):
                (sys_root / "class/block" / name).mkdir(parents=True)
            (sys_root / "class/block/nvme0n1p1/partition").write_text("1\n", encoding="utf-8")
            (proc / "diskstats").write_text(
                "259 0 nvme0n1 1 0 100 0 1 0 200 0 0 0 0 0 0 0\n"
                "259 1 nvme0n1p1 1 0 900 0 1 0 900 0 0 0 0 0 0 0\n"
                "7 0 loop0 1 0 800 0 1 0 800 0 0 0 0 0 0 0\n",
                encoding="utf-8",
            )
            counters = read_disk_counters(proc, sys_root)
            self.assertEqual(counters.read_bytes, 100 * 512)
            self.assertEqual(counters.write_bytes, 200 * 512)

    def test_absent_power_and_services_are_safe_states(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proc = root / "proc"
            sys_root = root / "sys"
            etc_root = root / "etc"
            proc.mkdir()
            def unavailable(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
                return subprocess.CompletedProcess([], 1, "", "")

            collectors = SystemCollectors(proc, sys_root, etc_root, command_runner=unavailable)
            self.assertEqual(
                collectors.power(),
                {
                    "power_source": "unknown",
                    "battery_percent": None,
                    "battery_state": "unknown",
                },
            )
            services = collectors.services()
            self.assertEqual(services["service_ufw"], "unknown")
            self.assertEqual(services["service_fortivpn"], "unknown")
            self.assertEqual(services["service_numberpad"], "unknown")
            self.assertEqual(services["service_ntfy"], "unknown")
            self.assertEqual(services["service_monitors"], "unknown")
            self.assertEqual(collectors.updates(), {"updates_count": None, "updates_status": "unknown"})


if __name__ == "__main__":
    unittest.main()
