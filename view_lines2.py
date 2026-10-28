with open(r'k:\dev\vibe-coding\musicbee-mcp-server\scripts\openrouter_agent_loop.py', 'r') as f:
    lines = f.readlines()
for i, line in enumerate(lines, 1):
    if 2058 <= i <= 2121:
        print(f'{i}: {line}', end='')