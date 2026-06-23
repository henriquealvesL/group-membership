# Group Membership

**Grupo 26**
- Felipe Goulart
- Henrique Alves

Implementação do building block de **Group Membership** para sistemas distribuídos, com detecção de falhas por heartbeat e protocolo de mudança de visão coordenado.

## Pré-requisitos

- Python 3.10+

Não há dependências externas — o projeto usa apenas a biblioteca padrão do Python (sockets TCP, threading).

## Estrutura do Projeto

```
group_membership/
├── membership.py       # Componente principal (GroupMembership)
├── view.py             # Representação de uma View (snapshot do grupo)
├── failure_detector.py # Detector de falhas baseado em heartbeat
└── messages.py         # Serialização de mensagens (JSON sobre TCP)

chat.py                 # Aplicação de chat distribuído
demo.py                 # Demo básica (somente views, sem chat)
Makefile                # Atalhos para execução
```

## Como Executar

### Aplicação de Chat (chat.py)

Abra cada nó em um terminal separado:

```bash
# Terminal 1 — cria a sala de chat (primeiro nó)
python3 chat.py --name Alice --port 5001 --start

# Terminal 2 — entra via nó existente
python3 chat.py --name Bob --port 5002 --join localhost:5001

# Terminal 3
python3 chat.py --name Charlie --port 5003 --join localhost:5001

# Terminal 4
python3 chat.py --name Diana --port 5004 --join localhost:5001
```

Comandos disponíveis no chat:
- `/members` — mostra membros online
- `/view` — mostra detalhes da view atual
- `/help` — mostra ajuda
- `/quit` — sai do chat

### Demo Básica (demo.py)

Demonstra o protocolo de membership sem a camada de chat:

```bash
# Terminal 1 — cria o grupo
python3 demo.py --port 5001 --start

# Terminal 2 — entra no grupo
python3 demo.py --port 5002 --join localhost:5001

# Terminal 3
python3 demo.py --port 5003 --join localhost:5001
```

### Usando o Makefile

```bash
# Chat
make alice    # Terminal 1
make bob      # Terminal 2
make charlie  # Terminal 3
make diana    # Terminal 4

# Demo
make demo-node1   # Terminal 1
make demo-node2   # Terminal 2
make demo-node3   # Terminal 3
```

## Testando Falhas

- **Saída graciosa:** pressione `Ctrl+C` em qualquer terminal. O nó notifica os demais antes de sair.
- **Crash simulado:** mate o processo com `Ctrl+Z` + `kill -9` (Linux/Mac) ou feche o terminal abruptamente. O detector de falhas identificará a ausência de heartbeat após ~4 segundos.

## Funcionamento

1. **Detector de Falhas:** cada processo envia heartbeats (a cada 1s) para todos os membros. Se nenhum heartbeat é recebido em 4s, o membro é considerado suspeito.
2. **Eleição de líder:** o membro com menor `(host, port)` na view atual é o líder — determinístico, sem eleição explícita.
3. **Protocolo de Mudança de View:**
   - Líder recebe trigger (join/leave/crash)
   - Envia `VIEW_PROPOSAL` para todos os membros da nova view
   - Coleta `VIEW_ACK` de todos
   - Broadcast de `VIEW_INSTALL` — todos instalam a nova view
