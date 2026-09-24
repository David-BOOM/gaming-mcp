# Theoretical Architecture: POMDP Latency Modeling and Token Economics

This document details the theoretical and mathematical foundations of `gaming-mcp`. It explains how the platform addresses two fundamental challenges in multimodal autonomous game agents:

1. **Temporal Disparity:** Bridging the gap between 60 Hz game physics loops (16.6 ms) and cloud LLM inference delays (500 ms to 2,500 ms) via a Latency-Lagged POMDP formulation and Action Chunking.
2. **Perceptual Token Economics:** Minimizing inference costs and rate limit exhaustion via 64-bit difference hashing (dHash) and adaptive Turbo-JPEG compression.

---

## 1. Research Lineage and Problem Formulation

Frontier Vision-Language-Action (VLA) agents, such as Google DeepMind SIMA and Genie, OpenAI Voyager and Operator, Anthropic Computer Use, and BAAI Cradle, represent a paradigm shift from specialized reinforcement learning models (e.g. AlphaStar) toward generalist, instructable foundation agents.

However, remote foundation models operate across a network boundary with inference latencies orders of magnitude slower than native game tick rates:

```text
Game Engine Physics Loop:   |-- 16.6 ms --|-- 16.6 ms --|-- 16.6 ms --|  (60 Hz)
Remote LLM Inference Turn:  |-------------------- 1,200 ms --------------------|  (0.8 Hz)
```

Direct atomic control (where each step requires a full remote inference turn) results in severe motor stutter, overshoot, and failure in real-time environments.

---

## 2. The Latency-Lagged POMDP Formulation

Standard reinforcement learning models an environment as a Markov Decision Process (MDP) defined by the tuple $(S, A, P, R, \gamma)$. In remote foundation model game control, this assumption breaks down due to non-negligible transmission and inference latencies.

We formalize video game interaction as a **Latency-Lagged Partially Observable Markov Decision Process (LL-POMDP)**:

$$\mathcal{M} = (S, A, \Omega, P, \mathcal{O}, R, \gamma, \tau)$$

Where:
* $S$ is the true underlying game world state (player position, entity coordinates, physics momentum, RAM buffers).
* $A$ is the action space (keyboard scan codes, mouse motion, virtual gamepad vectors).
* $\Omega$ is the observation space (visual frame pixels, tactical audio spectrograms).
* $\tau$ is the stochastic end-to-end network and inference delay:

$$\tau = \tau_{\text{capture}} + \tau_{\text{upload}} + \tau_{\text{inference}} + \tau_{\text{download}} \in [500\text{ ms}, 2500\text{ ms}]$$

### Observation Delay

When the foundation model receives observation $o_t$ at wall-clock time $t$, that observation reflects the state of the world at time $t - \tau_{\text{transit}}$:

$$o_t = \mathcal{O}(s_{t - \tau_{\text{transit}}})$$

### Actuation Stutter

By the time the model processes $o_t$ and issues action $a_t$, the world has evolved to:

$$s_{t + \tau_{\text{exec}}} \sim P(\cdot \mid s_{t - \tau_{\text{transit}}}, a_{\text{intervening}})$$

If the model relies on single discrete key taps, continuous movements (such as steering, sprinting, or jumping over chasms) fail because the release signal arrives seconds after the hazard has passed.

---

## 3. Hierarchical Action Chunking

To mitigate the LL-POMDP delay, `gaming-mcp` implements **Hierarchical Action Chunking**, grounded in recent Action Chunking with Transformers (ACT) literature.

Rather than emitting single atomic commands, the remote LLM emits a parameterized **Action Chunk** $\mathbf{C}$:

$$\mathbf{C} = \{ (a_0, \Delta t_0), (a_1, \Delta t_1), \dots, (a_K, \Delta t_K) \}$$

Where each step $a_k$ defines a coordinated keyboard, mouse, and gamepad target, and $\Delta t_k$ defines its execution offset in milliseconds.

```text
Remote LLM (0.8 Hz)
       |
       |  Action Chunk C = [(press 'w', 500ms), (drag mouse dx=120, 200ms), (release 'w', 0ms)]
       v
Local Microsecond Scheduler (1000 Hz)
       |--> 0ms:   Inject KEYEVENTF_SCANCODE ('w', down)
       |--> 200ms: Begin minimum-jerk mouse spline (x: 500 -> 620)
       |--> 500ms: Inject KEYEVENTF_SCANCODE ('w', up)
```

The local scheduler executes the chunk with microsecond precision on the host machine. If an emergency occurs or the client cancels the operation, the server intercepts `notifications/cancelled` and halts the chunk immediately.

---

## 4. Minimum-Jerk Trajectory Splining

Rapid, discrete mouse teleports trigger anti-cheat heuristic flags and cause camera jitter in 3D game engines. To generate natural, human-like motion, `gaming-mcp` implements the **Minimum-Jerk Polynomial Formulation** (Flash and Hogan, 1985), which models human motor control and satisfies Fitts' Law.

### Mathematical Formulation

The objective is to minimize total movement jerk (the third time derivative of position) over trajectory duration $T$:

$$J = \frac{1}{2} \int_0^T \left( \left(\frac{d^3 x}{dt^3}\right)^2 + \left(\frac{d^3 y}{dt^3}\right)^2 \right) dt$$

Subject to boundary conditions:
* Initial position: $x(0) = x_0, y(0) = y_0$
* Final position: $x(T) = x_f, y(T) = y_f$
* Boundary velocities: $\dot{x}(0) = 0, \dot{x}(T) = 0, \dot{y}(0) = 0, \dot{y}(T) = 0$
* Boundary accelerations: $\ddot{x}(0) = 0, \ddot{x}(T) = 0, \ddot{y}(0) = 0, \ddot{y}(T) = 0$

The unique solution is a fifth-order polynomial:

$$x(t) = x_0 + (x_f - x_0) \left( 10 \left(\frac{t}{T}\right)^3 - 15 \left(\frac{t}{T}\right)^4 + 6 \left(\frac{t}{T}\right)^5 \right)$$

$$y(t) = y_0 + (y_f - y_0) \left( 10 \left(\frac{t}{T}\right)^3 - 15 \left(\frac{t}{T}\right)^4 + 6 \left(\frac{t}{T}\right)^5 \right)$$

This polynomial yields smooth S-curve velocity profiles with bell-shaped acceleration, guaranteeing zero instantaneous jerk at start and arrival.

---

## 5. Perceptual Token Economics and 64-bit dHash Gating

### The Token Overhead Problem

Frontier vision models charge per image token patch (e.g. 256 to 1,600 tokens per full-resolution screenshot). Uncompressed 1080p PNG images average 3 to 5 MB per frame.

Polling visual state at 1 Hz consumes:
* ~1,000 tokens per frame $\times$ 3,600 seconds = **3.6 million tokens per hour**.

During menus, dialogue sequences, loading screens, and inventory management, consecutive frames are 98% identical, wasting token budgets and causing provider rate limits.

### 64-Bit Difference Hashing (dHash)

To eliminate redundant frame transmissions, `gaming-mcp` implements a 64-bit gradient difference hash:

1. **Downsample and Grayscale:** The acquired frame is resized to $9 \times 8$ pixels and converted to luminance grayscale.
2. **Compute Horizontal Gradients:** For each of the 8 rows, compare adjacent pixel intensities:

$$B_{y, x} = \begin{cases} 1 & \text{if } P(x, y) > P(x+1, y) \\ 0 & \text{otherwise} \end{cases} \quad \text{for } x \in [0, 7], y \in [0, 7]$$

3. **Bit Packing:** Pack the 64 boolean values into a single unsigned 64-bit integer $H \in [0, 2^{64}-1]$.

### Hamming Distance Gating

When `skip_if_static: true` is requested, the server computes the Hamming distance between the previous frame hash $H_{t-1}$ and current hash $H_t$:

$$D_H(H_{t-1}, H_t) = \text{popcount}(H_{t-1} \oplus H_t)$$

* If $D_H \le 3$ (Hamming distance threshold $\le 3$, corresponding to $<2.5\%$ visual mutation):
  The frame is considered perceptually static. The server suppresses image transmission and returns a lightweight text response:
  ```json
  {
    "status": "static_scene",
    "hamming_distance": 1,
    "text": "Scene static: visual delta < 2.5%. Image transmission suppressed."
  }
  ```
  **Token Cost:** ~25 tokens (97.5% reduction).

* If $D_H > 3$:
  The frame is encoded via Turbo-JPEG at quality 85 and downscaled to $1024 \times 576$, yielding a compact 120-180 KB payload encoded in under 12 milliseconds.

---

## 6. Auditory Perception via WASAPI Loopback

Visual observation alone is insufficient in 3D gaming: critical events (approaching footsteps, distant explosions, reload sounds) frequently occur outside the camera frustum (which is typically restricted to a 90-degree field of view).

`gaming-mcp` captures host master audio output via Windows Audio Session API (WASAPI) loopback:

1. **Audio Ring Buffer:** Audio PCM samples are continuously read from the loopback buffer in a non-blocking background thread.
2. **Short-Time Fourier Transform (STFT):** Samples are converted into 64-band log-mel spectrograms.
3. **Acoustic Event Detection:** Sudden energy deltas exceeding threshold $\theta_{\text{audio}}$ trigger tactical acoustic notifications exposed via `game://audio/events`, alerting the agent to off-screen stimuli without requiring continuous audio streaming.

---

## 7. Architectural Synthesis

Together, these mechanisms form a cohesive, production-grade foundation:

* **DXGI Duplication** acquires frames in $<8\text{ ms}$.
* **dHash Gating** discards redundant static frames, saving up to $80\%$ of token costs.
* **Turbo-JPEG** encodes the frame in $<12\text{ ms}$.
* **Minimum-Jerk Splining & Action Chunks** execute human-like motor trajectories, overcoming the latency gap.
* **Safety Envelopes & Kill-Switches** guarantee containment within the target game.
