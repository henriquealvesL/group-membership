# ── Nós individuais (abra cada um em um terminal separado) ───
alice:
	python3 chat.py --name Alice --port 5001 --start

bob:
	python3 chat.py --name Bob --port 5002 --join localhost:5001

charlie:
	python3 chat.py --name Charlie --port 5003 --join localhost:5001

diana:
	python3 chat.py --name Diana --port 5004 --join localhost:5001

# ── Demo básica (sem chat, só views) ────────────────────────
demo-node1:
	python3 demo.py --port 5001 --start

demo-node2:
	python3 demo.py --port 5002 --join localhost:5001

demo-node3:
	python3 demo.py --port 5003 --join localhost:5001
