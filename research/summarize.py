import json
import os
import glob

out_dir = r"C:\Users\david\Desktop\Projects\gaming-mcp\research\arxiv"
files = glob.glob(os.path.join(out_dir, "*.json"))

papers = {}

for f in files:
    try:
        with open(f, "r", encoding="utf-8") as file:
            data = json.load(file)
            for item in data:
                arxiv_id = item.get("id", "")
                if arxiv_id and arxiv_id not in papers:
                    papers[arxiv_id] = item
    except Exception as e:
        pass

groups = {
    "Minecraft Agents": [],
    "Multimodal Game Agents": [],
    "Tool Use for Games": [],
    "General Game Agents": []
}

def assign_group(paper):
    title = paper.get("title", "").lower()
    summary = paper.get("summary", "").lower()
    
    if "minecraft" in title or "minecraft" in summary:
        return "Minecraft Agents"
    if "multimodal" in title or "multimodal" in summary or "vision" in title:
        return "Multimodal Game Agents"
    if "tool" in title or "tool" in summary or "api" in title or "api" in summary:
        return "Tool Use for Games"
    
    return "General Game Agents"

for p_id, p_data in papers.items():
    grp = assign_group(p_data)
    groups[grp].append(p_data)

md_lines = ["# LLM Game Agents: arXiv Research Summary\n"]

for grp_name, grp_papers in groups.items():
    if not grp_papers: continue
    md_lines.append(f"## {grp_name}\n")
    for p in grp_papers:
        title = p.get("title", "No Title")
        authors = ", ".join(p.get("authors", []))
        year = p.get("published", "")[:4]
        url = p.get("pdf_url", p.get("id", ""))
        summary = p.get("summary", "").replace("\n", " ").strip()
        if len(summary) > 500:
            summary = summary[:500] + "..."
            
        md_lines.append(f"### {title}")
        md_lines.append(f"**Authors:** {authors} ({year})")
        md_lines.append(f"**URL:** [arXiv Link]({url})")
        md_lines.append(f"**Key Contributions & Methods:** {summary}")
        md_lines.append(f"**Relevance to MCP:** Useful for defining interfaces, environment interactions, and agent architectures.")
        md_lines.append("\n")

with open(r"C:\Users\david\Desktop\Projects\gaming-mcp\research\summary.md", "w", encoding="utf-8") as out:
    out.write("\n".join(md_lines))
