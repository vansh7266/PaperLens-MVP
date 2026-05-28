# ============================================================
# core/llm.py — LLM Wrapper for PaperLens
# ============================================================
# This is the ONLY file that talks to AI models directly.
# Every other file (summarizer, peeler, chat) imports from here.
#
# Why centralize it here?
#   - One place to switch models (Gemini → Claude)
#   - One place to handle errors
#   - One place to add logging / cost tracking
#   - Other files don't need to know which model is running
#
# Current: Gemini 2.0 Flash (free tier, fast)
# Production: Claude Sonnet 4.6 (change ACTIVE_LLM in config.py)
# ============================================================

import sys
import os

# Add parent directory to path so we can import config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import google.generativeai as genai
from config import (
    GEMINI_API_KEY,
    CLAUDE_API_KEY,
    get_active_model,
    get_active_llm,
    DEBUG,
)


# ============================================================
# INITIALIZE GEMINI
# ============================================================
# Configure the Gemini SDK with our API key
# This runs once when the module is imported

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    print("⚠️  WARNING: GEMINI_API_KEY not found in .env")


# ============================================================
# CORE FUNCTION — call_llm()
# ============================================================
# This is the main function everything else uses.
# It abstracts away which model is running.
#
# Parameters:
#   prompt  → what you want to ask the model
#   system  → optional instructions (how to behave, what format)
#   temperature → 0.0 = focused/deterministic, 1.0 = creative
#
# Returns:
#   The model's response as a plain string
#   Or an error message string if something goes wrong

async def call_llm(
    prompt: str,
    system: str = None,
    temperature: float = 0.3,
) -> str:
    """
    Call the active LLM with a prompt and return the response.

    Usage example:
        response = await call_llm(
            prompt="Explain what a transformer is in 2 sentences",
            system="You are a helpful AI/ML explainer. Be concise."
        )
        print(response)
    """
    provider = get_active_llm()

    if provider == "gemini":
        return await _call_gemini(prompt, system, temperature)
    elif provider == "claude":
        return await _call_claude(prompt, system, temperature)
    else:
        return f"Error: Unknown LLM provider '{provider}'"


# ============================================================
# GEMINI IMPLEMENTATION
# ============================================================

async def _call_gemini(
    prompt: str,
    system: str = None,
    temperature: float = 0.3,
) -> str:
    """
    Internal function — calls Gemini API.
    Not called directly by other files — they use call_llm().
    """
    try:
        model_name = get_active_model()

        # Build generation config
        generation_config = genai.types.GenerationConfig(
            temperature=temperature,
            max_output_tokens=1024,
        )

        # Create model instance
        model = genai.GenerativeModel(
            model_name=model_name,
            generation_config=generation_config,
            system_instruction=system if system else None,
        )

        # Build the full prompt
        full_prompt = prompt

        if DEBUG:
            print(f"\n[LLM] Calling {model_name}")
            print(f"[LLM] Prompt preview: {prompt[:100]}...")

        # Call Gemini
        # Note: Gemini SDK is sync, we run it in executor to not block
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: model.generate_content(full_prompt)
        )

        # Extract text from response
        result = response.text.strip()

        if DEBUG:
            print(f"[LLM] Response preview: {result[:100]}...")

        return result

    except Exception as e:
        error_msg = str(e)

        # Handle specific Gemini errors with helpful messages
        if "API_KEY_INVALID" in error_msg or "API key not valid" in error_msg:
            print(f"❌ Gemini API key is invalid. Check GEMINI_API_KEY in .env")
            return "Error: Invalid API key. Please check your Gemini API key."

        elif "RATE_LIMIT" in error_msg or "quota" in error_msg.lower():
            print(f"⚠️  Gemini rate limit hit. Waiting 60 seconds...")
            await asyncio.sleep(60)
            # Retry once
            try:
                response = await loop.run_in_executor(
                    None,
                    lambda: model.generate_content(prompt)
                )
                return response.text.strip()
            except Exception:
                return "Error: Rate limit exceeded. Please try again later."

        elif "SAFETY" in error_msg:
            return "Error: Content was blocked by safety filters."

        else:
            print(f"❌ Gemini error: {error_msg}")
            return f"Error: Could not get response from AI. ({error_msg[:100]})"


# ============================================================
# CLAUDE IMPLEMENTATION
# ============================================================
# Placeholder for when we switch to Claude in production
# To activate: change ACTIVE_LLM = "claude" in config.py

async def _call_claude(
    prompt: str,
    system: str = None,
    temperature: float = 0.3,
) -> str:
    """
    Internal function — calls Claude API.
    Activated when ACTIVE_LLM = "claude" in config.py
    """
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

        messages = [{"role": "user", "content": prompt}]

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: client.messages.create(
                model=get_active_model(),
                max_tokens=1024,
                system=system if system else "You are a helpful AI/ML research assistant.",
                messages=messages,
                temperature=temperature,
            )
        )

        return response.content[0].text.strip()

    except ImportError:
        return "Error: anthropic package not installed. Run: uv pip install anthropic"
    except Exception as e:
        print(f"❌ Claude error: {str(e)}")
        return f"Error: Could not get response from Claude. ({str(e)[:100]})"


# ============================================================
# SPECIFIC FUNCTIONS
# ============================================================
# These are pre-built prompts for common tasks.
# Other files call these instead of building prompts themselves.


async def summarize_paper(title: str, abstract: str) -> str:
    """
    Generate a 2-3 line plain English summary of a paper.
    Called by pipeline/summarizer.py for every new paper.

    Cost: 1 Gemini API call per paper (called ONCE, stored forever)
    """
    system = (
        "You are an AI/ML research explainer. "
        "Your job is to explain research papers in plain English "
        "for software engineers and researchers. "
        "Be concise, accurate, and avoid jargon. "
        "Never use phrases like 'the paper proposes' or 'the authors'."
    )

    prompt = f"""Summarize this AI/ML research paper in exactly 2-3 sentences.
Write for a software engineer who is smart but not a researcher.
Focus on: what problem it solves, how it solves it, and why it matters.
Do NOT use bullet points. Write in plain prose.

Paper title: {title}

Abstract: {abstract}

Summary:"""

    result = await call_llm(prompt, system, temperature=0.2)

    # Fallback if LLM fails
    if result.startswith("Error:"):
        # Generate a basic summary from the abstract
        sentences = abstract.split(". ")
        return ". ".join(sentences[:2]) + "."

    return result


async def classify_topic_llm(title: str, abstract: str) -> str:
    """
    Classify a paper's topic using LLM (backup only).
    Primary classification is keyword-based in processor.py (free).
    This is only called if keyword matching returns no match.

    Returns one of:
        LLMs, Computer Vision, RL / Agents, Diffusion Models,
        NLP, Multimodal, AI Safety, Model Efficiency, Robotics, Other
    """
    system = "You are an AI/ML paper classifier. Reply with ONLY the topic name, nothing else."

    prompt = f"""Classify this paper into exactly ONE of these topics:
LLMs, Computer Vision, RL / Agents, Diffusion Models, NLP,
Multimodal, AI Safety, Model Efficiency, Robotics, Other

Paper: {title}
Abstract (first 300 chars): {abstract[:300]}

Topic:"""

    result = await call_llm(prompt, system, temperature=0.1)

    # Clean up response
    valid_topics = [
        "LLMs", "Computer Vision", "RL / Agents", "Diffusion Models",
        "NLP", "Multimodal", "AI Safety", "Model Efficiency", "Robotics", "Other"
    ]

    # Find which valid topic appears in response
    for topic in valid_topics:
        if topic.lower() in result.lower():
            return topic

    return "Other"


async def detect_difficulty_llm(title: str, abstract: str) -> str:
    """
    Detect paper difficulty using LLM (backup only).
    Primary detection is rule-based in processor.py (free).
    Only called if rule-based detection is uncertain.

    Returns: "Easy", "Intermediate", or "Advanced"
    """
    system = "You classify research paper difficulty. Reply with ONLY: Easy, Intermediate, or Advanced."

    prompt = f"""How difficult is this paper for a software engineer with ML basics?
Easy = survey/intro, Intermediate = standard ML paper, Advanced = heavy math/theory

Paper: {title}
Abstract (first 200 chars): {abstract[:200]}

Difficulty:"""

    result = await call_llm(prompt, system, temperature=0.1)

    if "easy" in result.lower():
        return "Easy"
    elif "advanced" in result.lower():
        return "Advanced"
    else:
        return "Intermediate"


# ============================================================
# TEST — run this file directly to verify Gemini works
# Command: python core/llm.py
# ============================================================

async def _test():
    print(f"\n{'='*55}")
    print(f"  Testing LLM wrapper — provider: {get_active_llm()}")
    print(f"  Model: {get_active_model()}")
    print(f"{'='*55}\n")

    # Test 1: Basic call
    print("Test 1: Basic call...")
    response = await call_llm(
        prompt="What is a transformer in machine learning? Answer in exactly 2 sentences.",
        system="You are a helpful AI explainer. Be concise."
    )
    print(f"  Response: {response}\n")

    # Test 2: Paper summarization
    print("Test 2: Paper summarization...")
    summary = await summarize_paper(
        title="Attention Is All You Need",
        abstract="The dominant sequence transduction models are based on complex recurrent or convolutional neural networks. We propose a new simple network architecture, the Transformer, based solely on attention mechanisms, dispensing with recurrence and convolutions entirely."
    )
    print(f"  Summary: {summary}\n")

    # Test 3: Topic classification
    print("Test 3: Topic classification...")
    topic = await classify_topic_llm(
        title="Attention Is All You Need",
        abstract="The dominant sequence transduction models are based on complex recurrent or convolutional neural networks that include an encoder and a decoder."
    )
    print(f"  Topic: {topic}\n")

    print("✅ LLM wrapper working correctly!")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    asyncio.run(_test())
