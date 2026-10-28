with open(r'k:\dev\vibe-coding\musicbee-mcp-server\scripts\openrouter_agent_loop.py', 'r') as f:
    content = f.read()
    idx = content.find('staged, unresolved')
    print('Found at:', idx)
    print(content[max(0, idx-300):idx+100])