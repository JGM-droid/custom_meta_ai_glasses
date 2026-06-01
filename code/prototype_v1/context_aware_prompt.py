from memory_manager import format_recent_memory

def build_prompt():
    memory = format_recent_memory()

    return f"""
You are a wearable AI assistant.

Recent observations:
{memory}

Analyze the current image.

Explain:
1. What the user is looking at
2. What task they are performing
3. How this relates to recent activity
4. The next 3 practical steps
"""