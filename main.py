"""
main.py
-------
Entry point for the AI-Aware Microkernel simulation.

Right now this just validates the project structure and common types.
Each phase will add more here until the full simulation runs from this file.
"""

import sys
import os

# Add project root to path so all imports work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.types import (
    ProcessorType, ProcessState, Priority, TaskClass,
    MemoryType, AcceleratorState, MessageType,
    MemoryRegion, IPCMessage, InferenceRequest, InferenceResult,
    TelemetryEvent, SimConstants
)


def print_header(title: str):
    width = 60
    print("=" * width)
    print(f"  {title}")
    print("=" * width)


def print_section(title: str):
    print(f"\n--- {title} ---")


def validate_types():
    """
    Instantiate every type and confirm it works.
    This is our first 'test' — basic smoke test.
    """
    print_header("AI-Aware Microkernel OS — Type Validation")

    # --- Enums ---
    print_section("Processor Types (maps to Snapdragon SoC compute units)")
    for p in ProcessorType:
        print(f"  {p.name:<12} → {p.value}")

    print_section("Process States")
    for s in ProcessState:
        print(f"  {s.name:<12} → {s.value}")

    print_section("Task Classes (used by AI-aware scheduler)")
    for t in TaskClass:
        print(f"  {t.name:<16} → {t.value}")

    print_section("Accelerator States (NPU/DSP power states)")
    for a in AcceleratorState:
        print(f"  {a.name:<14} → {a.value}")

    print_section("Memory Types")
    for m in MemoryType:
        print(f"  {m.name:<12} → {m.value}")

    # --- Data structures ---
    print_section("Sample MemoryRegion (simulates ION/CMA allocation)")
    region = MemoryRegion(
        region_id=1,
        base_address=0x1000,
        size=256,
        owner_pid=-1,
        mem_type=MemoryType.AI_BUFFER,
        is_free=True
    )
    print(f"  region_id    : {region.region_id}")
    print(f"  base_address : 0x{region.base_address:04X}")
    print(f"  size         : {region.size} bytes")
    print(f"  owner_pid    : {region.owner_pid} (−1 = unowned)")
    print(f"  mem_type     : {region.mem_type.value}")
    print(f"  is_free      : {region.is_free}")

    print_section("Sample IPCMessage (simulates Binder/QMI message)")
    msg = IPCMessage(
        message_id=42,
        sender_pid=1,
        receiver_pid=2,
        msg_type=MessageType.COMMAND,
        payload="RUN_INFERENCE:mobilenet_v3"
    )
    print(f"  message_id   : {msg.message_id}")
    print(f"  sender_pid   : {msg.sender_pid}")
    print(f"  receiver_pid : {msg.receiver_pid}")
    print(f"  msg_type     : {msg.msg_type.value}")
    print(f"  payload      : {msg.payload}")

    print_section("Sample InferenceRequest (simulates SNPE/QNN call)")
    req = InferenceRequest(
        request_id=100,
        model_id="mobilenet_v3",
        input_size=602112,      # 224 * 224 * 3 * 4 bytes (float32)
        latency_sla=5.0,        # Must complete within 5ms
        requester_pid=5,
        preferred_hw=ProcessorType.NPU
    )
    print(f"  request_id   : {req.request_id}")
    print(f"  model_id     : {req.model_id}")
    print(f"  input_size   : {req.input_size:,} bytes")
    print(f"  latency_sla  : {req.latency_sla}ms")
    print(f"  requester_pid: {req.requester_pid}")
    print(f"  preferred_hw : {req.preferred_hw.value}")

    print_section("Simulation Constants")
    print(f"  MAX_PROCESSES      : {SimConstants.MAX_PROCESSES}")
    print(f"  TOTAL_MEMORY_BYTES : {SimConstants.TOTAL_MEMORY_BYTES}")
    print(f"  IPC_QUEUE_DEPTH    : {SimConstants.IPC_QUEUE_DEPTH}")
    print(f"  TICK_DURATION_MS   : {SimConstants.TICK_DURATION_MS}ms")
    print(f"  AI_BUFFER_ALIGN    : {SimConstants.AI_BUFFER_ALIGN} bytes")

    print("\n" + "=" * 60)
    print("  ✓ All types validated. Project structure is correct.")
    print("  Next step: MemoryManager module.")
    print("=" * 60)


if __name__ == "__main__":
    validate_types()
