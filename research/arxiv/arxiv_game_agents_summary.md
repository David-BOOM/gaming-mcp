# LLM Game Agents: arXiv Research Summary

*Note: Due to strict HTTP 406 blocks from the arXiv API for automated queries from this IP, this summary was synthesized from existing knowledge of seminal papers in the field of LLMs and game-playing agents, directly matching the themes requested.*

## Minecraft Agents

### Voyager: An Open-Ended Embodied Agent with Large Language Models
**Authors:** Guanzhi Wang, Yuqi Xie, Yunfan Jiang, Ajay Mandlekar, Chaowei Xiao, Yuke Zhu, Linxi Fan, Anima Anandkumar (2023)
**URL:** [arXiv Link](https://arxiv.org/abs/2305.16291)
**Key Contributions & Methods:** Introduces Voyager, the first LLM-powered embodied lifelong learning agent in Minecraft that continuously explores the world, acquires diverse skills, and makes novel discoveries without human intervention. Voyager consists of an automatic curriculum that maximizes exploration, an ever-growing skill library of executable code for complex behaviors, and a new iterative prompting mechanism that incorporates environment feedback, execution errors, and self-verification for program improvement.
**Relevance to MCP:** Highly relevant for building an MCP server that requires skill library management, code execution, and environment feedback loops.

### Ghost in the Minecraft (GITM): Generally Capable Agents for Open-World Environments via Large Language Models
**Authors:** Haoqi Yuan, Chi Zhang, Hongcheng Wang, Feiyang Xie, Penglin Cai, Hao Dong, Zongqing Lu (2023)
**URL:** [arXiv Link](https://arxiv.org/abs/2305.17144)
**Key Contributions & Methods:** Proposes a novel framework, Ghost in the Minecraft (GITM), that integrates LLMs with text-based knowledge and memories to create generally capable agents in Minecraft. It maps text to low-level keyboard/mouse actions, bypassing the need for handwritten APIs.
**Relevance to MCP:** Relevant for low-level action schemas and translating high-level goals to discrete game inputs.

## Multimodal Game Agents

### SIMA: Scaling Instructable Agents Across Many Virtual Worlds
**Authors:** SIMA Team, DeepMind (2024)
**URL:** [arXiv Link](https://arxiv.org/abs/2404.10179)
**Key Contributions & Methods:** Introduces SIMA (Scalable Instructable Multiworld Agent), an agent trained to follow natural-language instructions across a variety of 3D virtual environments and video games. SIMA is trained on human gameplay data across 9 different games, learning to map language and image observations directly to keyboard and mouse actions without accessing internal game state.
**Relevance to MCP:** Crucial for designing multimodal MCP schemas that take screenshots as input and output generic HID actions.

### Genie: Generative Interactive Environments
**Authors:** Jake Bruce, et al. (2024)
**URL:** [arXiv Link](https://arxiv.org/abs/2402.15391)
**Key Contributions & Methods:** Presents Genie, a foundation world model trained from unlabeled internet videos that can generate an interactive variety of action-controllable virtual worlds from a single image prompt. While technically an environment generator, it showcases how latent actions can be learned without ground-truth labels.
**Relevance to MCP:** Useful for understanding latent action spaces and predictive modeling of game states for planning.

## General Game Agents

### Generative Agents: Interactive Simulacra of Human Behavior
**Authors:** Joon Sung Park, Joseph C. O'Brien, Carrie J. Cai, Meredith Ringel Morris, Percy Liang, Michael S. Bernstein (2023)
**URL:** [arXiv Link](https://arxiv.org/abs/2304.03442)
**Key Contributions & Methods:** Introduces generative agents—computational software agents that simulate believable human behavior. The agents inhabit a 2D RPG game world (Smallville). The architecture includes an observation loop, memory stream, reflection, and planning components.
**Relevance to MCP:** The memory, reflection, and planning architecture is a canonical design pattern for multi-agent game servers.

### Playing Atari with Deep Reinforcement Learning
**Authors:** Volodymyr Mnih, et al. (2013)
**URL:** [arXiv Link](https://arxiv.org/abs/1312.5602)
**Key Contributions & Methods:** The seminal paper introducing DQN for Atari. While not an LLM paper, it established the standard interface for AI interacting with games (pixels in, discrete actions out).
**Relevance to MCP:** The Gym interface (observation, reward, done, info) remains the standard for wrapping games in MCP.

## Tool Use and Computer Use for Games

### Cradle: Empowering Foundation Agents towards General Computer Control
**Authors:** Weihao Dong, et al. (2024)
**URL:** [arXiv Link](https://arxiv.org/abs/2403.03186)
**Key Contributions & Methods:** Introduces Cradle, a framework giving foundation models the ability to control computers. It plays Red Dead Redemption 2 purely through visual observation and generic mouse/keyboard control, outperforming previous specialized agents.
**Relevance to MCP:** Perfect reference for a general Computer Use MCP server designed for high-fidelity PC games.

### Gorilla: Large Language Model Connected with Massive APIs
**Authors:** Shishir G. Patil, Tianjun Zhang, Xin Wang, Joseph E. Gonzalez (2023)
**URL:** [arXiv Link](https://arxiv.org/abs/2305.15334)
**Key Contributions & Methods:** Explores how LLMs can effectively use vast numbers of APIs. Demonstrates fine-tuning LLaMA to write API calls with high accuracy, overcoming hallucination issues.
**Relevance to MCP:** Highly relevant for an MCP server that exposes hundreds of specific game mod APIs or memory reading functions.
