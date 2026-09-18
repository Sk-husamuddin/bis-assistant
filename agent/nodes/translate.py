import os
from agent.state import GraphState
from agent.debug import is_verbose

try:
    from groq import Groq
except Exception:
    Groq = None  # type: ignore

LANG_NAMES = {"hi": "Hindi", "te": "Telugu", "ta": "Tamil"}

def _call_groq_translate(text: str, language_name: str) -> str | None:
    api_key = os.getenv("GROQ_API_KEY", "")
    try:
        from dotenv import load_dotenv
        load_dotenv()
        api_key = os.getenv("GROQ_API_KEY", api_key)
    except Exception:
        pass
    if not api_key:
        return None
    if Groq is None:
        print("[translate] Groq SDK not available")
        return None
    try:
        model = os.getenv("GROQ_SYNTHESIS_MODEL", "openai/gpt-oss-120b")
        prompt = (
            f"Translate the following into {language_name}. Preserve all IS standard numbers (e.g. IS 2347), "
            f"scheme names (CRS, ISI, MSCS, FMCS, Hallmarking), and citation markers like [1] exactly as they "
            f"appear in English, unchanged. Keep markdown structure intact. Return ONLY the translated text, no preamble or explanation."
        )
        client = Groq(api_key=api_key)
        if is_verbose():
            try:
                # Recompute max_tokens for logging (same logic as below)
                _est = int(len(text) * 1.2 + 600)
                _mt = max(1200, min(4096, _est))
                if _mt < 2048 and len(text) > 800:
                    _mt = 2048
                print("\n" + "=" * 60)
                print(f"[DEBUG][translate] target={language_name} | model={model} | input_len={len(text)} chars | max_tokens={_mt} (dynamic)")
                print(f"[DEBUG][translate] SYSTEM prompt:\n{prompt[:1000]}")
                print(f"\n[DEBUG][translate] USER text to translate (first 1500 chars):\n{text[:1500]}")
                print("=" * 60 + "\n")
            except Exception:
                pass
        # FIX: Indic scripts need 1.5-2x tokens vs English for same content.
        # Previous 1000 truncated Hindi (263 chars vs 1200 English, finish_reason=length).
        # Use dynamic sizing per spec 3b: estimate from English length, with generous flat fallback.
        # Flat 4096 would always request 4096+prompt tokens and worsen TPM/TPD rate limits (8000 TPM, 200k TPD).
        # Dynamic: max(1200, min(4096, int(len(text) * 1.2 + 600))) — len 1200->2040, len 2000->3000, len 3000->4096 cap.
        # Keeps requested tokens proportional to actual need, reducing rate-limit hits while preventing truncation.
        estimated = int(len(text) * 1.2 + 600)
        max_tokens = max(1200, min(4096, estimated))
        # Also ensure at least 2048 for very short inputs that still expand in Indic
        if max_tokens < 2048 and len(text) > 800:
            max_tokens = 2048
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": text},
            ],
            temperature=0.2,
            max_tokens=max_tokens,
        )
        # Capture finish_reason and usage for diagnosis (smoking gun for truncation)
        try:
            finish_reason = getattr(resp.choices[0], "finish_reason", None)
            usage = getattr(resp, "usage", None)
            prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
            completion_tokens = getattr(usage, "completion_tokens", None) if usage else None
            total_tokens = getattr(usage, "total_tokens", None) if usage else None
        except Exception:
            finish_reason = None
            prompt_tokens = completion_tokens = total_tokens = None
        out = (resp.choices[0].message.content or "").strip()
        # Detect mid-sentence truncation (before reaching frontend)
        truncated_mid_sentence = False
        if out:
            stripped = out.rstrip()
            # If finish_reason is length and last char is not sentence terminator, likely cut mid-sentence
            if finish_reason == "length":
                truncated_mid_sentence = stripped[-1] not in ".!?।।]\"'`»”’"
            else:
                # Heuristic: if out ends without punctuation and is long, flag
                truncated_mid_sentence = False
        if is_verbose():
            try:
                print("\n" + "=" * 60)
                print(f"[DEBUG][translate] RAW model response (first 2000 chars):\n{out[:2000]}")
                print(f"[DEBUG][translate] translated_len={len(out)} chars | finish_reason={finish_reason!r} | prompt_tokens={prompt_tokens} completion_tokens={completion_tokens} total={total_tokens}")
                print(f"[DEBUG][translate] truncated_mid_sentence={truncated_mid_sentence}")
                if finish_reason == "length":
                    print(f"[DEBUG][translate] *** TRUNCATED: finish_reason='length' — hit max_tokens=1000 ***")
                print("=" * 60 + "\n")
            except Exception:
                pass
        # Also always print a concise line even when not verbose for diagnosis? No, terminal only when verbose per spec.
        # Store finish_reason for programmatic diagnosis if needed (not in state, just log)
        return out if out else None
    except Exception as e:
        print(f"[translate] groq call failed: {e}")
        return None

def translate_node(state: GraphState) -> dict:
    target = state.get("target_language", "en")
    if target == "en":
        if is_verbose():
            try:
                print(f"[DEBUG][translate] target_language=en → no translation, returning None")
            except Exception:
                pass
        return {"translated_answer": None}
    answer = state.get("answer", "")
    if not answer:
        if is_verbose():
            try:
                print(f"[DEBUG][translate] empty answer for lang={target} → returning None")
            except Exception:
                pass
        return {"translated_answer": None}
    language_name = LANG_NAMES.get(target, target)
    if is_verbose():
        try:
            print(f"[DEBUG][translate] node invoked: target={target} ({language_name}) | answer_len={len(answer)}")
        except Exception:
            pass
    translated = _call_groq_translate(answer, language_name)
    if translated is None:
        # Fallback: return English answer when Groq not available / failed — don't crash
        print(f"[translate] fallback to English for lang={target} (missing GROQ_API_KEY or API error)")
        if is_verbose():
            try:
                print(f"[DEBUG][translate] fallback translated_answer len={len(answer)} (English)")
            except Exception:
                pass
        return {"translated_answer": answer}
    if is_verbose():
        try:
            print(f"[DEBUG][translate] final translated_answer len={len(translated)} (first 300 chars): {translated[:300]!r}")
        except Exception:
            pass
    return {"translated_answer": translated}
