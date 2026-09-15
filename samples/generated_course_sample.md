# Distributed Consensus & Fault-Tolerant State Machines with Raft and Rust

> [!IMPORTANT]
> **Prerequisites**: Familiarity with systems programming in Rust (ownership, lifetimes, async/await with Tokio), TCP/IP socket abstractions, and state machine replication basics.

---

## Executive Summary
This enterprise syllabus equips engineers with the theoretical principles and concrete implementation skills required to construct a linearizable, fault-tolerant replicated state machine utilizing the **Raft consensus algorithm** in asynchronous Rust.

---

## Module 1: Raft Consensus Invariants & Leader Election

### 1.1 The State Machine Safety Invariant
The fundamental guarantee of Raft is **State Machine Safety**: if a server has applied an entry at a given index to its state machine, no other server will ever apply a different log entry for the same index.

```rust
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum NodeRole {
    Follower { current_leader: Option<u64> },
    Candidate { votes_received: usize },
    Leader { next_index: Vec<u64>, match_index: Vec<u64> },
}

pub struct RaftNode {
    pub id: u64,
    pub current_term: u64,
    pub voted_for: Option<u64>,
    pub role: NodeRole,
}
```

> [!NOTE]
> Randomized election timeouts (typically 150ms – 300ms) prevent persistent split-vote livelocks in candidate state transitions.

---

## Module 2: Write-Ahead Log (WAL) Replication & Linearizability

### 2.1 AppendEntries RPC Protocol
Leaders append entries to their local log and broadcast `AppendEntries` RPCs in parallel to followers:

```rust
use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize, Debug)]
pub struct AppendEntriesRequest<T> {
    pub term: u64,
    pub leader_id: u64,
    pub prev_log_index: u64,
    pub prev_log_term: u64,
    pub entries: Vec<T>,
    pub leader_commit: u64,
}
```

> [!WARNING]
> Never commit an entry from a previous term solely by counting replicas. An entry is safe only once committed in the *current* leader term.

---

## Module 3: Production Failure Modes & Joint Consensus

### 3.1 Network Asymmetry & Partitions
In real-world datacenters, asymmetric partitions occur where node A can send packets to B, but B cannot reply. To mitigate pre-vote disruptions, modern Raft employs a **Pre-Vote Phase**:
1. Candidates query peers before incrementing their term.
2. Only if a quorum confirms the current leader is unreachable does the candidate trigger a full term bump.

---

## Knowledge Check & Hands-on Lab

### Conceptual Checkpoint
1. **Why does Raft disallow committing log entries from previous terms by counting replicas?**
   - *Explanation*: A leader could overwrite an uncommitted entry from a prior term if a network partition is healed before quorum consensus on current-term log entries is finalized.
2. **What occurs during an asymmetric partition if Pre-Vote is disabled?**
   - *Explanation*: A partitioned node repeatedly times out, increments its term to high values, and disrupts the healthy leader when reconnected.

### Hands-on Lab Exercise: Write an In-Memory Term & Heartbeat Guard
```rust
pub fn handle_append_entries(
    node: &mut RaftNode,
    req: AppendEntriesRequest<String>,
) -> Result<bool, &'static str> {
    if req.term < node.current_term {
        return Ok(false); // Reject stale leader
    }
    if req.term > node.current_term {
        node.current_term = req.term;
        node.role = NodeRole::Follower { current_leader: Some(req.leader_id) };
    }
    Ok(true)
}
```
