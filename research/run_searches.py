import subprocess
import json
import sys

script = r"C:\Users\david\.gemini\config\plugins\science\skills\literature_search_arxiv\scripts\search_arxiv.py"
out_dir = r"C:\Users\david\Desktop\Projects\gaming-mcp\research\arxiv"

queries = [
    ('search1.json', 'abs:"large language model" AND abs:game AND abs:agent'),
    ('search2.json', 'abs:"game playing" AND abs:"language model"'),
    ('search3.json', 'ti:"game agent" AND abs:"LLM"'),
    ('search4.json', 'abs:"computer use" AND abs:agent AND abs:game'),
    ('search5.json', 'abs:Minecraft AND abs:"language model" AND abs:agent'),
    ('search6.json', 'abs:"multimodal agent" AND abs:game'),
    ('search7.json', 'abs:"game environment" AND abs:"reinforcement learning" AND abs:"language model"'),
    ('search8.json', 'ti:Voyager OR ti:SIMA OR ti:Genie AND abs:game AND abs:agent'),
    ('search9.json', 'abs:"tool use" AND abs:agent AND abs:game'),
    ('search10.json', 'abs:"model context protocol" OR abs:MCP AND abs:agent')
]

for filename, query in queries:
    cmd = [
        "uv", "run", script,
        "--query", query,
        "--max_results", "10",
        "--sort_by", "submittedDate",
        "--sort_order", "descending"
    ]
    print(f"Running {filename}...")
    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            with open(rf"{out_dir}\{filename}", "w", encoding="utf-8") as f:
                f.write(res.stdout)
        else:
            print(f"Error for {filename}:", res.stderr)
    except Exception as e:
        print(f"Exception for {filename}:", e)
