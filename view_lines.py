import sys
path = r'k:\dev\vibe-coding\musicbee-mcp-server\scripts\openrouter_agent_loop.py'
with open(path, 'r') as f:
    lines = f.readlines()
print(f'Total lines: {len(lines)}')
print('--- Lines 1930-1970 ---')
for i in range(1929, min(1980, len(lines))):
    print(f'{i+1}: {lines[i].rstrip()}')