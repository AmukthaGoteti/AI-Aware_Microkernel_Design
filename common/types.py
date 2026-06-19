"""
common/types.py
---------------
Shared types, enums, and data structures for the AI-Aware Microkernel simulation.

Industry context:
    In real Qualcomm firmware, this is equivalent to a shared header like qcom_types.h
    or kernel_types.h — a single source of truth for all data types used across
    the kernel, drivers, and user-space services.

    Every subsystem imports from here. Nothing is defined twice.
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional
import time


# =============================================================================
# PROCESSOR TYPES
# =============================================================================
# In a Qualcomm Snapdragon SoC, there are multiple processor types on one chip.
# Each type is optimized for different work:
#   - BIG_CPU  : Cortex-X cores — maximum performance, highest power
#   - LITTLE_CPU: Cortex-A efficiency cores — background tasks, low power
#   - DSP      : Hexagon DSP — signal processing, sensor fusion, some AI
#   - NPU      : Hexagon Tensor Accelerator — neural network inference
#   - GPU      : Adreno — graphics + general compute (OpenCL/Vulkan)
# =============================================================================

class ProcessorType(Enum):
    BIG_CPU    = "BIG_CPU"      # Performance core (Cortex-X equivalent)
    LITTLE_CPU = "LITTLE_CPU"   # Efficiency core (Cortex-A equivalent)
    DSP        = "DSP"          # Hexagon DSP
    NPU        = "NPU"          # Neural Processing Unit
    GPU        = "GPU"          # Graphics Processing Unit


# =============================================================================
# PROCESS STATES
# =============================================================================
# A process (or task in firmware terminology) moves through these states
# during its lifetime. This is the classic OS state machine.
#
# READY     → Task is waiting to be scheduled. It has everything it needs.
# RUNNING   → Task is currently executing on a processor core.
# BLOCKED   → Task is waiting for something (IPC message, memory, device).
# SUSPENDED → Task has been paused by the OS (e.g. low power mode).
# TERMINATED → Task has finished or been killed. Resources will be freed.
#
# Industry note: In Qualcomm's Hexagon RTOS, these map to:
#   READY=TASK_READY, RUNNING=TASK_RUNNING, BLOCKED=TASK_WAIT, etc.
# =============================================================================

class ProcessState(Enum):
    READY      = "READY"
    RUNNING    = "RUNNING"
    BLOCKED    = "BLOCKED"
    SUSPENDED  = "SUSPENDED"
    TERMINATED = "TERMINATED"


# =============================================================================
# TASK PRIORITY LEVELS
# =============================================================================
# Priority determines which task the scheduler runs first when multiple
# tasks are READY at the same time.
#
# CRITICAL  : Hard real-time tasks. Sensor interrupts, safety watchdogs.
#             Must preempt everything else immediately.
# HIGH      : AI inference with strict latency SLA. System services.
# NORMAL    : Regular application tasks.
# LOW       : Background tasks. Cleanup, logging, non-urgent work.
# IDLE      : Only runs when nothing else is READY. Power management loops.
#
# Industry note: Qualcomm's RTOS uses numeric priorities (0=highest).
#   We use named levels for readability. They map to numbers internally.
# =============================================================================

class Priority(Enum):
    CRITICAL = 0    # Highest — runs first always
    HIGH     = 1
    NORMAL   = 2
    LOW      = 3
    IDLE     = 4    # Lowest — only runs when nothing else can


# =============================================================================
# TASK CLASSIFICATION
# =============================================================================
# The scheduler uses this to decide WHICH processor type to use.
# This is the AI-aware part of our OS.
#
# REAL_TIME       → Goes to BIG_CPU with preemptive scheduling
# AI_INFERENCE    → Routed to NPU first, DSP fallback, CPU last resort
# SIGNAL_PROCESS  → Goes to DSP (sensor data, audio, modem processing)
# COMPUTE_HEAVY   → Goes to BIG_CPU or GPU
# BACKGROUND      → Goes to LITTLE_CPU to save power
#
# Industry note: This maps to Qualcomm's task tagging in the Hexagon SDK
#   and to Android's process group classification used by EAS.
# =============================================================================

class TaskClass(Enum):
    REAL_TIME      = "REAL_TIME"       # Hard deadline, must not miss
    AI_INFERENCE   = "AI_INFERENCE"    # Neural network forward pass
    SIGNAL_PROCESS = "SIGNAL_PROCESS"  # DSP workload
    COMPUTE_HEAVY  = "COMPUTE_HEAVY"   # CPU/GPU bound
    BACKGROUND     = "BACKGROUND"      # Low urgency


# =============================================================================
# MEMORY REGION TYPES
# =============================================================================
# Not all memory is equal. Different parts of the system use different memory.
#
# GENERAL     : Standard process heap/stack memory (DRAM)
# AI_BUFFER   : Large contiguous block for AI model weights + activations
#               Must be physically contiguous for DMA access by NPU/DSP
# IPC_SHARED  : Memory explicitly shared between two processes for fast IPC
# DEVICE_MEM  : Memory-mapped device registers (like reading a hardware register)
# SECURE      : TrustZone-protected memory — cannot be read by normal processes
#
# Industry note: Qualcomm uses the ION allocator and CMA (Contiguous Memory
#   Allocator) for AI_BUFFER-style allocations. SECURE maps to QSEE memory.
# =============================================================================

class MemoryType(Enum):
    GENERAL    = "GENERAL"
    AI_BUFFER  = "AI_BUFFER"
    IPC_SHARED = "IPC_SHARED"
    DEVICE_MEM = "DEVICE_MEM"
    SECURE     = "SECURE"


# =============================================================================
# ACCELERATOR STATES
# =============================================================================
# Hardware accelerators (NPU, DSP, GPU) are not always running.
# They have power states to save energy — critical in mobile devices.
#
# IDLE        : Powered on, no active work, ready to accept jobs immediately
# ACTIVE      : Currently executing a workload
# SLEEP       : Clocks gated, wakes in microseconds (shallow sleep)
# POWER_GATED : Fully powered off, takes milliseconds to wake (deep sleep)
# FAULT       : Something went wrong — needs reset before use
#
# Industry note: These map exactly to Qualcomm's power state management
#   for Hexagon DSP and NPU. The FastRPC framework manages wake/sleep cycles.
# =============================================================================

class AcceleratorState(Enum):
    IDLE        = "IDLE"
    ACTIVE      = "ACTIVE"
    SLEEP       = "SLEEP"
    POWER_GATED = "POWER_GATED"
    FAULT       = "FAULT"


# =============================================================================
# IPC MESSAGE TYPES
# =============================================================================
# Inter-Process Communication messages are typed. The IPC broker uses this
# to route and validate messages.
#
# COMMAND     : One process telling another to do something
# RESPONSE    : Reply to a COMMAND
# DATA        : Bulk data transfer (e.g. sensor readings, inference results)
# SIGNAL      : Lightweight notification (like a Unix signal but safer)
# ERROR       : Something went wrong, notifying another process
# =============================================================================

class MessageType(Enum):
    COMMAND  = "COMMAND"
    RESPONSE = "RESPONSE"
    DATA     = "DATA"
    SIGNAL   = "SIGNAL"
    ERROR    = "ERROR"


# =============================================================================
# FAULT TYPES
# =============================================================================
# Different kinds of failures the FaultManager will handle.

class FaultType(Enum):
    MEMORY_VIOLATION  = "MEMORY_VIOLATION"   # Process accessed memory it doesn't own
    ACCELERATOR_TIMEOUT = "ACCELERATOR_TIMEOUT" # NPU/DSP took too long
    PROCESS_CRASH     = "PROCESS_CRASH"      # Process hit an unrecoverable error
    IPC_OVERFLOW      = "IPC_OVERFLOW"       # Message queue full
    WATCHDOG_EXPIRE   = "WATCHDOG_EXPIRE"    # Process didn't check in on time


# =============================================================================
# CORE DATA STRUCTURES (dataclasses)
# =============================================================================
# These are the fundamental data objects passed between subsystems.
# Python dataclasses are like C structs — they hold data, not logic.
# In C++ (Level 2), these will become structs or simple classes.
# =============================================================================

@dataclass
class MemoryRegion:
    """
    Represents a single allocated block of simulated memory.

    C++ equivalent:
        struct MemoryRegion {
            uint32_t    region_id;
            uint32_t    base_address;
            size_t      size;
            int         owner_pid;
            MemoryType  mem_type;
            bool        is_free;
        };
    """
    region_id:    int
    base_address: int           # Simulated address (just an integer offset)
    size:         int           # Size in simulated bytes
    owner_pid:    int           # Which process owns this region (-1 = free)
    mem_type:     MemoryType
    is_free:      bool = True


@dataclass
class IPCMessage:
    """
    A message sent between processes via the IPC broker.

    Industry note: This is conceptually similar to a QMI (Qualcomm MSM Interface)
    message or an Android Binder transaction — a typed, sender-stamped payload
    delivered through a controlled broker.

    C++ equivalent:
        struct IPCMessage {
            int         message_id;
            int         sender_pid;
            int         receiver_pid;
            MessageType msg_type;
            std::string payload;
            double      timestamp;
        };
    """
    message_id:   int
    sender_pid:   int
    receiver_pid: int
    msg_type:     MessageType
    payload:      str           # Simplified: real systems use binary serialization
    timestamp:    float = field(default_factory=time.time)


@dataclass
class InferenceRequest:
    """
    A request to run an AI model on an accelerator.

    This is the fundamental unit of work for the AI Runtime Manager.
    In Qualcomm's world, this maps to a SNPE/QNN execute() call.

    Fields:
        request_id   : Unique ID for tracking
        model_id     : Which AI model to run (e.g. "mobilenet_v3", "whisper_tiny")
        input_size   : Size of input data in simulated bytes
        latency_sla  : Maximum acceptable latency in simulated ms
                       The scheduler uses this to pick the right accelerator.
        requester_pid: Which process is asking for inference
        preferred_hw : Optional hint for which accelerator to use
    """
    request_id:    int
    model_id:      str
    input_size:    int          # Simulated input tensor size in bytes
    latency_sla:   float        # Max acceptable latency in simulated ms
    requester_pid: int
    preferred_hw:  Optional[ProcessorType] = None


@dataclass
class InferenceResult:
    """
    The result returned after an inference completes.

    In real systems, this would contain the output tensor data.
    Here we simulate it with metadata only.
    """
    request_id:       int
    model_id:         str
    success:          bool
    accelerator_used: ProcessorType
    simulated_latency_ms: float   # How long it took (simulated)
    output_summary:   str         # Simplified result description


@dataclass
class TelemetryEvent:
    """
    A single telemetry data point emitted by any subsystem.

    Every subsystem emits these. The TelemetryEngine collects them
    and writes them to CSV for Python visualization.

    Industry note: Maps to Qualcomm's QDSS (Qualcomm Debug Subsystem)
    trace events and Linux ftrace events.
    """
    tick:       int             # Which simulation tick this happened on
    subsystem:  str             # Who emitted this (e.g. "Scheduler", "NPU")
    event_type: str             # What happened (e.g. "TASK_DISPATCHED")
    data:       dict            # Key-value pairs of metrics


# =============================================================================
# CONSTANTS
# =============================================================================

class SimConstants:
    """
    Simulation-wide constants.
    Centralised here so changing one value affects the whole simulation.

    In Qualcomm firmware, similar constants live in a platform config header.
    """
    MAX_PROCESSES:      int   = 64       # Maximum concurrent processes
    MAX_MEMORY_REGIONS: int   = 256      # Maximum memory allocations
    TOTAL_MEMORY_BYTES: int   = 1024     # Simulated total RAM (1024 "bytes")
    IPC_QUEUE_DEPTH:    int   = 32       # Max messages per process queue
    TICK_DURATION_MS:   float = 10.0     # One simulation tick = 10ms wall time
    AI_BUFFER_ALIGN:    int   = 64       # AI buffers must be 64-byte aligned
                                         # (mirrors real NPU DMA requirements)
