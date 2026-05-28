# VTool Llama Chat - Ejemplos de Uso

## Tabla de Contenidos

1. [Uso Básico](#uso-básico)
2. [Integración con Frontend Custom](#integración-con-frontend-custom)
3. [Consumir la API desde Python](#consumir-la-api-desde-python)
4. [Consumir desde JavaScript/Node.js](#consumir-desde-javascriptnodejs)
5. [Personalizaciones](#personalizaciones)

---

## Uso Básico

### 1. Iniciar el Servidor

```bash
# Opción A: Script helper
python run.py

# Opción B: Uvicorn directo
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Opción C: Python directo
python main.py
```

### 2. Acceder desde el Navegador

```
http://localhost:8000
```

### 3. Seleccionar un Personaje y Chatear

- Haz clic en un personaje en el sidebar
- Escribe un mensaje en el input
- Presiona Enter o haz clic en 📤
- Verás la respuesta en streaming

---

## Integración con Frontend Custom

### Usar la API en tu propio frontend

#### HTML Simple

```html
<!DOCTYPE html>
<html>
<head>
    <title>Mi Chat Personalizado</title>
</head>
<body>
    <div id="messages"></div>
    <input id="input" placeholder="Escribe aquí...">
    <button id="send">Enviar</button>

    <script>
        // Cargar personajes
        async function loadCharacters() {
            const res = await fetch('/api/characters');
            const chars = await res.json();
            console.log(chars);
        }

        // Enviar mensaje
        document.getElementById('send').addEventListener('click', async () => {
            const message = document.getElementById('input').value;
            
            const res = await fetch('/api/chat-stream', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: message,
                    character: 'Ares'  // Cambia según tu personaje
                })
            });

            const reader = res.body.getReader();
            const decoder = new TextDecoder();

            while (true) {
                const { value, done } = await reader.read();
                if (done) break;

                const text = decoder.decode(value);
                const lines = text.split('\n');
                
                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        const token = line.slice(6);
                        if (token !== '[DONE]') {
                            document.getElementById('messages').innerHTML += token;
                        }
                    }
                }
            }

            document.getElementById('input').value = '';
        });

        loadCharacters();
    </script>
</body>
</html>
```

#### React

```jsx
import React, { useState, useEffect } from 'react';

function ChatApp() {
    const [characters, setCharacters] = useState([]);
    const [current, setCurrent] = useState(null);
    const [messages, setMessages] = useState([]);
    const [input, setInput] = useState('');
    const [loading, setLoading] = useState(false);

    // Cargar personajes
    useEffect(() => {
        fetch('/api/characters')
            .then(r => r.json())
            .then(setCharacters);
    }, []);

    // Cargar personaje
    const loadCharacter = async (name) => {
        await fetch('/api/load-character', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ character: name })
        });
        setCurrent(name);
        setMessages([]);
    };

    // Enviar mensaje
    const sendMessage = async () => {
        if (!current || !input.trim()) return;

        setMessages([...messages, { role: 'user', text: input }]);
        setLoading(true);
        setInput('');

        const res = await fetch('/api/chat-stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: input,
                character: current
            })
        });

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let aiResponse = '';

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;

            const text = decoder.decode(value);
            const lines = text.split('\n');

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const token = line.slice(6);
                    if (token !== '[DONE]') {
                        aiResponse += token.replace(/\\n/g, '\n');
                        setMessages(prev => {
                            const copy = [...prev];
                            if (copy[copy.length - 1]?.role === 'assistant') {
                                copy[copy.length - 1].text = aiResponse;
                            } else {
                                copy.push({ role: 'assistant', text: aiResponse });
                            }
                            return copy;
                        });
                    }
                }
            }
        }

        setLoading(false);
    };

    return (
        <div style={{ display: 'grid', gridTemplateColumns: '200px 1fr', height: '100vh' }}>
            {/* Sidebar */}
            <div style={{ borderRight: '1px solid #ccc', padding: '10px' }}>
                <h3>Personajes</h3>
                {characters.map(char => (
                    <button
                        key={char.name}
                        onClick={() => loadCharacter(char.name)}
                        style={{
                            width: '100%',
                            padding: '8px',
                            marginBottom: '5px',
                            background: current === char.name ? '#3b82f6' : '#f0f0f0',
                            color: current === char.name ? 'white' : 'black',
                            border: 'none',
                            cursor: 'pointer'
                        }}
                    >
                        {char.name}
                    </button>
                ))}
            </div>

            {/* Chat */}
            <div style={{ display: 'flex', flexDirection: 'column' }}>
                <div style={{ flex: 1, overflow: 'auto', padding: '10px' }}>
                    {messages.map((msg, i) => (
                        <div
                            key={i}
                            style={{
                                textAlign: msg.role === 'user' ? 'right' : 'left',
                                marginBottom: '10px'
                            }}
                        >
                            <div
                                style={{
                                    display: 'inline-block',
                                    maxWidth: '60%',
                                    padding: '10px',
                                    borderRadius: '8px',
                                    background: msg.role === 'user' ? '#3b82f6' : '#e0e0e0',
                                    color: msg.role === 'user' ? 'white' : 'black'
                                }}
                            >
                                {msg.text}
                            </div>
                        </div>
                    ))}
                </div>

                <div style={{ padding: '10px', borderTop: '1px solid #ccc', display: 'flex', gap: '5px' }}>
                    <input
                        value={input}
                        onChange={e => setInput(e.target.value)}
                        onKeyPress={e => e.key === 'Enter' && sendMessage()}
                        placeholder="Escribe aquí..."
                        style={{ flex: 1, padding: '8px' }}
                    />
                    <button
                        onClick={sendMessage}
                        disabled={loading}
                        style={{
                            padding: '8px 15px',
                            background: '#3b82f6',
                            color: 'white',
                            border: 'none',
                            cursor: 'pointer'
                        }}
                    >
                        Enviar
                    </button>
                </div>
            </div>
        </div>
    );
}

export default ChatApp;
```

#### Vue.js

```vue
<template>
    <div class="app">
        <div class="sidebar">
            <h3>Personajes</h3>
            <button
                v-for="char in characters"
                :key="char.name"
                @click="loadCharacter(char.name)"
                :class="{ active: current === char.name }"
            >
                {{ char.name }}
            </button>
        </div>

        <div class="chat">
            <div class="messages">
                <div
                    v-for="(msg, i) in messages"
                    :key="i"
                    :class="['message', msg.role]"
                >
                    {{ msg.text }}
                </div>
            </div>

            <div class="input-area">
                <input
                    v-model="input"
                    @keypress.enter="sendMessage"
                    placeholder="Escribe aquí..."
                />
                <button @click="sendMessage" :disabled="loading">
                    Enviar
                </button>
            </div>
        </div>
    </div>
</template>

<script>
export default {
    data() {
        return {
            characters: [],
            current: null,
            messages: [],
            input: '',
            loading: false
        };
    },
    mounted() {
        this.loadCharacters();
    },
    methods: {
        async loadCharacters() {
            const res = await fetch('/api/characters');
            this.characters = await res.json();
        },
        async loadCharacter(name) {
            await fetch('/api/load-character', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ character: name })
            });
            this.current = name;
            this.messages = [];
        },
        async sendMessage() {
            if (!this.current || !this.input.trim()) return;

            const input = this.input;
            this.messages.push({ role: 'user', text: input });
            this.input = '';
            this.loading = true;

            const res = await fetch('/api/chat-stream', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: input,
                    character: this.current
                })
            });

            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let aiResponse = '';

            while (true) {
                const { value, done } = await reader.read();
                if (done) break;

                const text = decoder.decode(value);
                const lines = text.split('\n');

                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        const token = line.slice(6);
                        if (token !== '[DONE]') {
                            aiResponse += token.replace(/\\n/g, '\n');
                            if (this.messages[this.messages.length - 1]?.role === 'assistant') {
                                this.messages[this.messages.length - 1].text = aiResponse;
                            } else {
                                this.messages.push({ role: 'assistant', text: aiResponse });
                            }
                        }
                    }
                }
            }

            this.loading = false;
        }
    }
};
</script>

<style scoped>
.app {
    display: grid;
    grid-template-columns: 200px 1fr;
    height: 100vh;
}

.sidebar {
    border-right: 1px solid #ccc;
    padding: 10px;
}

.chat {
    display: flex;
    flex-direction: column;
}

.messages {
    flex: 1;
    overflow: auto;
    padding: 10px;
}

.message {
    margin-bottom: 10px;
}

.message.user {
    text-align: right;
}

.input-area {
    padding: 10px;
    border-top: 1px solid #ccc;
    display: flex;
    gap: 5px;
}

input {
    flex: 1;
    padding: 8px;
}

button {
    padding: 8px 15px;
    background: #3b82f6;
    color: white;
    border: none;
    cursor: pointer;
}
</style>
```

---

## Consumir la API desde Python

### Cliente Python Simple

```python
import requests

BASE_URL = "http://localhost:8000/api"

class VToolChatClient:
    def __init__(self, base_url=BASE_URL):
        self.base_url = base_url
        self.current_character = None

    def list_characters(self):
        """Obtiene lista de personajes."""
        res = requests.get(f"{self.base_url}/characters")
        return res.json()

    def load_character(self, name):
        """Carga un personaje."""
        res = requests.post(
            f"{self.base_url}/load-character",
            json={"character": name}
        )
        self.current_character = name
        return res.json()

    def chat(self, message):
        """Chat simple."""
        res = requests.post(
            f"{self.base_url}/chat",
            json={"message": message, "character": self.current_character}
        )
        return res.json()['response']

    def stream_chat(self, message):
        """Chat con streaming."""
        res = requests.post(
            f"{self.base_url}/chat-stream",
            json={"message": message, "character": self.current_character},
            stream=True
        )
        
        for line in res.iter_lines():
            if line:
                if line.startswith(b'data: '):
                    data = line[6:].decode()
                    if data != '[DONE]' and not data.startswith('[ERROR]'):
                        yield data

    def reset(self):
        """Reinicia el chat."""
        return requests.post(f"{self.base_url}/reset").json()

    def save_episode(self):
        """Guarda un episodio."""
        return requests.post(f"{self.base_url}/save-episode").json()

# Uso
if __name__ == "__main__":
    client = VToolChatClient()
    
    # Listar personajes
    chars = client.list_characters()
    print("Personajes:", [c['name'] for c in chars])
    
    # Cargar uno
    client.load_character("Ares")
    
    # Chat simple
    response = client.chat("Hola, ¿cómo estás?")
    print("Respuesta:", response)
    
    # Chat con streaming
    print("\nStreaming:")
    for token in client.stream_chat("Cuéntame una historia"):
        print(token, end="", flush=True)
```

### Cliente Asincrónico

```python
import aiohttp
import asyncio

class VToolChatAsyncClient:
    def __init__(self, base_url="http://localhost:8000/api"):
        self.base_url = base_url
        self.current_character = None
        self.session = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, *args):
        await self.session.close()

    async def list_characters(self):
        async with self.session.get(f"{self.base_url}/characters") as res:
            return await res.json()

    async def load_character(self, name):
        async with self.session.post(
            f"{self.base_url}/load-character",
            json={"character": name}
        ) as res:
            self.current_character = name
            return await res.json()

    async def stream_chat(self, message):
        async with self.session.post(
            f"{self.base_url}/chat-stream",
            json={"message": message, "character": self.current_character}
        ) as res:
            async for line in res.content:
                if line.startswith(b'data: '):
                    data = line[6:].decode()
                    if data != '[DONE]':
                        yield data

# Uso
async def main():
    async with VToolChatAsyncClient() as client:
        chars = await client.list_characters()
        print("Personajes:", [c['name'] for c in chars])
        
        await client.load_character("Ares")
        
        print("Streaming:")
        async for token in client.stream_chat("Hola"):
            print(token, end="", flush=True)

asyncio.run(main())
```

---

## Consumir desde JavaScript/Node.js

### Cliente Node.js

```javascript
// vtool-client.js
const fetch = require('node-fetch');

class VToolChatClient {
    constructor(baseUrl = 'http://localhost:8000/api') {
        this.baseUrl = baseUrl;
        this.currentCharacter = null;
    }

    async listCharacters() {
        const res = await fetch(`${this.baseUrl}/characters`);
        return res.json();
    }

    async loadCharacter(name) {
        const res = await fetch(`${this.baseUrl}/load-character`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ character: name })
        });
        this.currentCharacter = name;
        return res.json();
    }

    async chat(message) {
        const res = await fetch(`${this.baseUrl}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message,
                character: this.currentCharacter
            })
        });
        return (await res.json()).response;
    }

    async *streamChat(message) {
        const res = await fetch(`${this.baseUrl}/chat-stream`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message,
                character: this.currentCharacter
            })
        });

        const reader = res.body.getReader();
        const decoder = new TextDecoder();

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;

            const text = decoder.decode(value);
            const lines = text.split('\n');

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const data = line.slice(6);
                    if (data !== '[DONE]') {
                        yield data.replace(/\\n/g, '\n');
                    }
                }
            }
        }
    }
}

module.exports = VToolChatClient;
```

```javascript
// index.js
const VToolChatClient = require('./vtool-client');

(async () => {
    const client = new VToolChatClient();

    const chars = await client.listCharacters();
    console.log('Personajes:', chars.map(c => c.name));

    await client.loadCharacter('Ares');

    console.log('Streaming:');
    for await (const token of client.streamChat('Hola')) {
        process.stdout.write(token);
    }
    console.log();
})();
```

### Cliente Fetch (Navegador)

```javascript
// vtool-client.js (para navegador)
class VToolChatClient {
    constructor(baseUrl = '/api') {
        this.baseUrl = baseUrl;
        this.currentCharacter = null;
    }

    async listCharacters() {
        const res = await fetch(`${this.baseUrl}/characters`);
        return res.json();
    }

    async loadCharacter(name) {
        const res = await fetch(`${this.baseUrl}/load-character`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ character: name })
        });
        this.currentCharacter = name;
        return res.json();
    }

    async *streamChat(message) {
        const res = await fetch(`${this.baseUrl}/chat-stream`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message,
                character: this.currentCharacter
            })
        });

        const reader = res.body.getReader();
        const decoder = new TextDecoder();

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;

            const text = decoder.decode(value);
            const lines = text.split('\n');

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const data = line.slice(6);
                    if (data !== '[DONE]') {
                        yield data.replace(/\\n/g, '\n');
                    }
                }
            }
        }
    }
}

// Uso
const client = new VToolChatClient();
client.loadCharacter('Ares').then(() => {
    const messagesDiv = document.getElementById('messages');
    const input = document.getElementById('input');

    document.getElementById('send').onclick = async () => {
        const message = input.value;
        input.value = '';

        const userDiv = document.createElement('div');
        userDiv.textContent = `Tú: ${message}`;
        messagesDiv.appendChild(userDiv);

        const aiDiv = document.createElement('div');
        messagesDiv.appendChild(aiDiv);

        for await (const token of client.streamChat(message)) {
            aiDiv.textContent += token;
        }
    };
});
```

---

## Personalizaciones

### 1. Cambiar el Tema

Edit `index.html`:

```css
:root {
    --primary: #1a1a2e;
    --secondary: #16213e;
    --accent: #0f3460;
    --accent-light: #533483;
    --success: #06d6a0;
    --text-primary: #eaeaea;
    --text-secondary: #888888;
}
```

### 2. Agregar Sonido

```javascript
function playSound(url) {
    const audio = new Audio(url);
    audio.play();
}

// En chat
playSound('https://cdn.pixabay.com/download/audio/...');
```

### 3. Guardar Chats en localStorage

```javascript
function saveChat(character, messages) {
    localStorage.setItem(`chat_${character}`, JSON.stringify(messages));
}

function loadChat(character) {
    return JSON.parse(localStorage.getItem(`chat_${character}`)) || [];
}
```

### 4. Integrar Analytics

```javascript
function trackEvent(event, data) {
    navigator.sendBeacon('/api/analytics', JSON.stringify({
        event,
        data,
        timestamp: Date.now()
    }));
}

// En cada mensaje
trackEvent('message_sent', {
    character: currentCharacter,
    length: message.length
});
```

---

## Deploy

### Heroku

```bash
# Crear app
heroku create my-vtool-chat

# Configurar vars de entorno
heroku config:set MODEL_PATH=/path/to/models

# Deploy
git push heroku main
```

### Railway

```bash
# Install CLI
npm i -g @railway/cli

# Deploy
railway init
railway link
railway up
```

### DigitalOcean App Platform

```yaml
# app.yaml
services:
  - name: vtool-llama-chat
    github:
      repo: usuario/vtool-llama-chat
      branch: main
    build_command: pip install -r requirements.txt
    run_command: uvicorn main:app --host 0.0.0.0 --port $PORT
    http_port: 8000
    env:
      - key: PERSONAJES_DIR
        value: /mnt/personajes
```

---

¡Ahora tienes una aplicación web completa y extensible! 🚀

