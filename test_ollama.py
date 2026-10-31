# test_ollama.py
import ollama
resp = ollama.chat(model="qwen2.5:3b", messages=[{"role":"user","content":"Say hello."}])
print(resp.get("message", {}).get("content"))