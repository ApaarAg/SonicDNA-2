# SonicDNA User Testing Guide

Field guide for running controlled real-user testing sessions. Designed for the soft launch phase.

---

## Core Principle

> **Do NOT ask "is the UI good?" Ask "did this feel emotionally real?"**

The product's value lives in emotional authenticity, not interface polish. Every observation should trace back to whether the experience felt genuine.

---

## Tester Profiles

Recruit 5–15 testers across these categories. You don't need all categories filled — but you need variety.

| Profile | What to Watch For |
|---------|-------------------|
| **Music-heavy users** (100k+ Spotify minutes) | Do they trust the genome? Does it capture nuance? |
| **Emotionally engaged listeners** | Does the emotional sequencing resonate? Do they feel seen? |
| **Casual / passive listeners** | Can they complete onboarding? Is the quiz intimidating? |
| **Playlist-curation obsessives** | Does the playlist surprise them? Do they replay tracks? |
| **Regional music listeners** | Does the system handle non-English/non-Western music? |
| **Discovery-oriented listeners** | Do they find new music they actually like? |
| **Passive / ambient listeners** | Do they finish the session or drop off? |

---

## Session Structure (30–45 minutes)

### Phase 1: Unguided First Experience (15 min)

1. Give the tester the URL. Say only: *"This is a music experience. Explore it."*
2. Do NOT explain what it does or how to use it.
3. Observe silently. Note:
   - How long before they start the quiz
   - Whether they read the cinematic sections
   - When they first look confused
   - Whether they connect Spotify (and if they hesitate)
   - How they react to their archetype reveal
   - Whether they generate a playlist
   - Whether they play any tracks
   - Whether they share

### Phase 2: Guided Reflection (15 min)

Ask these questions in order. Let them talk — don't lead.

1. **"What was this?"** (Tests comprehension without priming)
2. **"Did anything feel emotionally real?"** (The core question)
3. **"Was there a moment you wanted to stop?"** (Friction detection)
4. **"Did the result feel like you?"** (Trust / authenticity)
5. **"Would you come back tomorrow?"** (Retention signal)
6. **"Would you send this to a friend?"** (Viral potential)
7. **"What felt confusing?"** (Confusion mapping)
8. **"If this were a real product, what would you pay for?"** (Value perception)

### Phase 3: Specific Flow Testing (10 min, optional)

If they didn't naturally discover these, guide them to:
- Spotify connect flow
- Playlist generation
- Share link creation
- Opening a share link in a different browser

---

## What to Observe (Not Ask)

These behavioral signals matter more than verbal feedback:

| Signal | How to Detect |
|--------|---------------|
| **Emotional reaction** | Facial expressions, verbal reactions ("oh", "wow", "hmm") |
| **Onboarding completion** | Did they finish the quiz or abandon? |
| **Spotify connect hesitation** | Time between seeing the button and clicking it |
| **Playlist resonance** | Do they listen to tracks or immediately skip? |
| **Replay behavior** | Do they go back to a track? |
| **Regeneration behavior** | Do they generate another playlist? |
| **Confusion points** | Where do they pause, squint, or scroll back? |
| **Trust perception** | Do they say "that's actually me" or "this is random"? |
| **Session duration** | How long do they stay engaged? |
| **Share behavior** | Do they create a share link? Do they actually send it? |

---

## Feedback Events to Monitor

These are already instrumented in the JSONL feedback system:

| Event Type | What It Tells You |
|------------|-------------------|
| `playlist_generated` | User reached playlist stage |
| `playlist_generation_failed` | Something broke |
| `track_focus` | User selected a specific track |
| `replay` | User replayed a track (strong engagement signal) |
| `share_created` | User wanted to share their identity |
| `frontend_runtime_fault` | Client-side error occurred |

### Reviewing Feedback Events

```powershell
# View recent feedback events
Get-Content backend\data\feedback_events.jsonl -Tail 50 | ConvertFrom-Json | Format-Table event_type, timestamp -AutoSize
```

---

## Post-Session Analysis

After each testing session, record:

1. **Tester profile** (which category)
2. **Completion status** (how far they got)
3. **Emotional authenticity score** (1–5, your subjective assessment)
4. **Key friction points** (specific moments)
5. **Verbatim quotes** (their exact words, especially emotional ones)
6. **Would return?** (yes/no/maybe)
7. **Would share?** (yes/no/maybe)

---

## Red Flags to Watch For

- Tester doesn't understand what the product is after using it
- Tester says "that's not me" about their archetype
- Tester abandons the quiz before finishing
- Tester connects Spotify but then immediately disconnects
- Tester generates a playlist but doesn't play any tracks
- Tester says "this is cool" but wouldn't come back

---

## Green Flags to Watch For

- Tester says "how did it know that?"
- Tester replays multiple tracks
- Tester screenshots their result
- Tester asks "can I send this to someone?"
- Tester spends >5 minutes in the playlist section
- Tester retakes the quiz to see if results change
- Tester says "this actually feels like me"
