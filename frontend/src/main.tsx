import { createSignal, For, onCleanup } from 'solid-js';
import { render } from 'solid-js/web';
import './styles.css';

type TaskStatus = 'pending' | 'running' | 'success' | 'error';

function App() {
  const [sourcePath, setSourcePath] = createSignal('');
  const [isRunning, setIsRunning] = createSignal(false);
  const [logs, setLogs] = createSignal<string[]>([]);
  const [resultUrl, setResultUrl] = createSignal<string | null>(null);
  const [error, setError] = createSignal<string | null>(null);
  const [taskId, setTaskId] = createSignal<string | null>(null);

  let logContainerRef: HTMLDivElement | undefined;
  let ws: WebSocket | null = null;
  let autoscroll = true;

  const closeSocket = () => {
    if (ws && ws.readyState < 2) {
      ws.close();
    }
    ws = null;
  };

  const appendLog = (line: string) => {
    setLogs((prev) => [...prev, line]);
    queueMicrotask(() => {
      if (!logContainerRef || !autoscroll) return;
      logContainerRef.scrollTop = logContainerRef.scrollHeight;
    });
  };

  const pollTaskStatus = async (id: string) => {
    const response = await fetch(`/api/result/${id}`);
    if (!response.ok) return;
    const payload = (await response.json()) as {
      status: TaskStatus;
      result_url: string | null;
      error: string | null;
    };
    if (payload.status === 'success') {
      setResultUrl(payload.result_url);
      setIsRunning(false);
    }
    if (payload.status === 'error') {
      setError(payload.error ?? 'Генерация завершилась с ошибкой');
      setIsRunning(false);
    }
  };

  const connectLogs = (id: string) => {
    const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${protocol}://${location.host}/ws/logs/${id}`);
    ws.onmessage = (event) => {
      const line = String(event.data);
      if (line.startsWith('__FINISHED__|')) {
        setResultUrl(line.slice('__FINISHED__|'.length));
        setIsRunning(false);
        return;
      }
      if (line === '__FAILED__') {
        setIsRunning(false);
        return;
      }
      appendLog(line);
    };
    ws.onclose = () => {
      pollTaskStatus(id).catch(() => {
        setError('Не удалось получить статус задачи после закрытия сокета');
      });
    };
  };

  const startGeneration = async () => {
    setError(null);
    setResultUrl(null);
    setLogs([]);
    closeSocket();

    const response = await fetch('/api/generate-docs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source_path: sourcePath() }),
    });

    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      setError(payload.detail ?? 'Не удалось запустить генерацию');
      return;
    }

    const payload = (await response.json()) as { task_id: string };
    setTaskId(payload.task_id);
    setIsRunning(true);
    appendLog(`Задача ${payload.task_id} запущена...`);
    connectLogs(payload.task_id);
  };

  onCleanup(() => closeSocket());

  return (
    <main class="app">
      <h1>Генератор документации кода</h1>

      <section class="panel controls">
        <label for="sourcePath">Путь к исходному коду</label>
        <input
          id="sourcePath"
          type="text"
          value={sourcePath()}
          onInput={(event) => setSourcePath(event.currentTarget.value)}
          placeholder="Например: /workspace/my-project"
        />
        <button onClick={startGeneration} disabled={isRunning() || sourcePath().trim().length === 0}>
          {isRunning() ? 'Генерация...' : 'Сгенерировать документацию'}
        </button>
      </section>

      <section class="panel">
        <h2>Логи выполнения</h2>
        <div
          class="logs"
          ref={logContainerRef}
          onScroll={(event) => {
            const el = event.currentTarget;
            const nearBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 24;
            autoscroll = nearBottom;
          }}
        >
          <For each={logs()}>{(line) => <div class="line">{line}</div>}</For>
        </div>
      </section>

      <section class="panel result">
        <h2>Результат</h2>
        <a
          href={resultUrl() ?? '#'}
          target="_blank"
          rel="noopener noreferrer"
          classList={{ disabled: !resultUrl() }}
        >
          Открыть документацию
        </a>
        {taskId() && <div class="task">Task ID: {taskId()}</div>}
      </section>

      {error() && <div class="error">{error()}</div>}
    </main>
  );
}

render(() => <App />, document.getElementById('root')!);
