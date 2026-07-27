# Diagrams

All diagrams are Mermaid — render natively on GitHub, or paste into https://mermaid.live.

## 1. System architecture

```mermaid
graph TB
    subgraph Client
        UI[Dashboard - index.html<br/>Chart.js + WebSocket client]
    end

    subgraph Server["FastAPI (main.py)"]
        REST[REST endpoints]
        WS[WebSocket /ws]
        LOOP[Simulation loop<br/>asyncio task]
    end

    subgraph Kernel["Kernel (kernel.py)"]
        SCHED[Scheduler]
        MEM[MemoryManager]
        IPC[IPCManager]
        IRQ[InterruptController]
        DEV[DeviceManager]
        DL[Deadlock: RAG + Banker's]
        FS[FileSystem]
        SEC[SecurityManager]
        NET[NetworkStack]
    end

    subgraph AI["AI Layer"]
        PRED[TrendPredictor / AnomalyDetector]
        MON[AISystemMonitor]
        CHAT[ChatAssistant]
    end

    UI <--> WS
    UI --> REST
    REST --> Kernel
    LOOP --> Kernel
    LOOP --> WS
    Kernel --> AI
    CHAT --> Kernel
    MON --> PRED
```

## 2. Microkernel communication (IPC boundary enforcement)

```mermaid
graph LR
    P1[Process: shell] -.request via kernel.-> K((Kernel / IPCManager))
    P2[Process: logger] -.request via kernel.-> K
    P3[Process: ai_daemon] -.request via kernel.-> K
    K --> MB1[Mailbox P1]
    K --> MB2[Mailbox P2]
    K --> MB3[Mailbox P3]
    K --> PIPE[Pipe buffer]
    K --> SHM[Shared segment]

    style K fill:#161f2d,stroke:#5ec8f8,color:#fff
    P1 -. "no direct channel" .-x P2
```

*Processes never hold a reference to each other — every arrow terminates at the kernel's `IPCManager`, which is the architectural point of this diagram.*

## 3. Scheduling decision sequence (AI mode)

```mermaid
sequenceDiagram
    participant T as Tick Loop
    participant S as Scheduler
    participant P as Ready Queue (PCBs)
    participant UI as Dashboard

    T->>S: pick_next(ready_queue, tick)
    S->>S: check hard starvation override (>=20 ticks waited?)
    alt starving process exists
        S-->>T: return starving process + reason
    else no hard starvation
        loop for each ready process
            S->>S: predict_burst() via exponential smoothing
            S->>S: compute score = w1*burst + w2*priority - w3*starve
        end
        S->>S: sort by score, pick minimum
        S-->>T: return chosen process + reason
    end
    T->>UI: broadcast snapshot (running, ai_reason)
    UI->>UI: render running box + ready queue chips
```

## 4. Memory access / page fault sequence

```mermaid
sequenceDiagram
    participant Proc as Running Process
    participant MM as MemoryManager
    participant F as Frame Pool
    participant PT as Page Table

    Proc->>MM: access_page(pid, page_table, page, tick)
    MM->>PT: check entry.present
    alt page present
        MM->>F: update last_used_tick / ref_bit / use_count
        MM-->>Proc: HIT (or PREFETCH_HIT)
    else page fault
        MM->>F: get_free_or_evict()
        alt no free frame
            F->>F: select_victim() per policy (FIFO/LRU/LFU/Clock)
            F->>PT: clear evicted page's present flag
        end
        MM->>PT: mark page present, assign frame
        MM-->>Proc: FAULT
    end
    MM->>MM: _ai_prefetch(): update Markov transition counts,<br/>speculatively load predicted next page
```

## 5. Deadlock detection flow

```mermaid
flowchart TD
    A[Process requests resource] --> B{Resource held by another process?}
    B -- No --> C[Grant immediately]
    B -- Yes --> D[Add wait-for edge in RAG]
    D --> E[Run DFS cycle detection]
    E --> F{Cycle found?}
    F -- Yes --> G[Report deadlock: circular wait chain]
    F -- No --> H[Run Banker's safety check before granting]
    H --> I{Safe sequence exists?}
    I -- Yes --> C
    I -- No --> J[Deny request - would create unsafe state]
    D --> K[DeadlockMonitor samples blocked ratio]
    K --> L[AI trend analysis: rising contention?]
    L --> M[Early warning: medium/high risk]
```

## 6. AI Scheduler decision-weight breakdown

```mermaid
pie showData
    title AI Scheduler Score Weights
    "Predicted burst (0.55)" : 55
    "Priority (0.25)" : 25
    "Starvation avoidance (0.20)" : 20
```

## 7. Boot sequence

```mermaid
flowchart LR
    A[POST: hardware descriptors] --> B[Init interrupt controller]
    B --> C[Init memory manager]
    C --> D[Mount root filesystem]
    D --> E[Start IPC broker]
    E --> F[Start security subsystem]
    F --> G[Bring up network loopback]
    G --> H[Start AI system monitor]
    H --> I[Start scheduler AI mode]
    I --> J[Spawn default processes:<br/>shell, file_manager, calculator,<br/>sensor, logger, ai_daemon, idle]
    J --> K[Enter multitasking mode]
```

## 8. UML class overview (simplified)

```mermaid
classDiagram
    class PCB {
        +int pid
        +str name
        +ProcessState state
        +int priority
        +int burst_time
        +int remaining_burst
        +float predicted_burst
        +str ai_reason
        +log(tick, event)
        +record_burst_sample()
    }
    class Scheduler {
        +Algorithm algorithm
        +int quantum
        +pick_next(ready_queue, tick) PCB
        +compute_quantum(proc) int
        -_ai_select(queue, tick) PCB
    }
    class MemoryManager {
        +int total_frames
        +ReplacementPolicy policy
        +access_page(pid, table, page, tick) dict
        -_ai_prefetch(pid, table, page, tick)
    }
    class Kernel {
        +int tick_count
        +dict processes
        +tick() dict
        +snapshot() dict
        +spawn_process(...)
        +kill_process(pid)
    }
    class AISystemMonitor {
        +cpu_overload_prediction() dict
        +memory_exhaustion_prediction() dict
        +recommend_policy(processes, algo) dict
        +health_score(...) dict
    }
    class ChatAssistant {
        +answer(question) str
    }

    Kernel --> Scheduler
    Kernel --> MemoryManager
    Kernel --> AISystemMonitor
    Kernel "1" --> "*" PCB
    AISystemMonitor --> ChatAssistant : referenced by
    Scheduler --> PCB : selects
```
