# AI-Aware Microkernel OS Simulation

A simulation of a microkernel operating system with heterogeneous processor scheduling
and AI accelerator management, inspired by Qualcomm Snapdragon SoC architecture.

## Project Goal

To learn and demonstrate:
- Microkernel OS design principles
- Heterogeneous task scheduling (CPU + DSP + NPU)
- AI inference pipeline management
- Firmware and embedded systems concepts relevant to Qualcomm careers

## Architecture Overview

```
User Space Services:  AI Runtime | Device Manager | Telemetry | Security
                              IPC (message passing only)
Microkernel Core:     Process Manager | Memory Manager | Scheduler | IPC Broker
                              Hardware Abstraction Layer
Simulated Hardware:   BIG_CPU | LITTLE_CPU | DSP | NPU | GPU | Memory
```

## Qualcomm Relevance

| Simulation Component | Qualcomm Equivalent |
|---|---|
| ProcessManager       | Hexagon RTOS task manager |
| MemoryManager        | ION allocator / CMA |
| IPCBroker            | FastRPC / Binder / QMI |
| Scheduler            | Energy-Aware Scheduler (EAS) |
| AIRuntimeManager     | SNPE / QNN inference engine |
| AcceleratorManager   | Hexagon NPU / Adreno KMD |
| TelemetryEngine      | Snapdragon Profiler / QDSS |

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install matplotlib
python3 main.py
```

## Development Phases

- [x] Phase 1: Project skeleton + common types
- [x] Phase 2: MemoryManager
- [ ] Phase 3: ProcessManager
- [ ] Phase 4: IPCBroker + Scheduler
- [ ] Phase 5: AcceleratorManager + AIRuntimeManager
- [ ] Phase 6: TelemetryEngine + SimulationEngine
- [ ] Phase 7: Python dashboard
