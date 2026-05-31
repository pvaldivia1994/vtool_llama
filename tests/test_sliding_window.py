"""
Simula el sliding window del deque para history_limit=5.
"""
from collections import deque

# Con history_limit=5, maxlen = 5 + 2 = 7 (system + 5 history + 1 extra)
d = deque(maxlen=7)
d.append({"role": "system", "content": "sys"})

print("Sliding window con history_limit=5 (maxlen=7):")
print(f"Estado inicial: {len(d)} mensajes\n")

for i in range(8):
    d.append({"role": "user", "content": f"user_msg_{i}"})
    d.append({"role": "assistant", "content": f"asst_{i}"})
    user_msgs = [m["content"] for m in d if m["role"] == "user"]
    print(f"Turno {i+1}: total={len(d)} | users={user_msgs}")

print("\n---\nVerificacion:")
print("Turno 5 deberia tener: sys, user_0..4, asst_0..4 = 11 msgs")
print("Turno 6 deberia tener: sys, user_1..5, asst_1..5 = 11 msgs (rotaron user_0 y asst_0)")
