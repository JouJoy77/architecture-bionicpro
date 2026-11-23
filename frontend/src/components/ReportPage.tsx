import React, { useEffect, useState } from 'react';

type Session = { username: string; can_report: boolean; csrf_token: string };

async function errorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (body.detail?.code === 'period_not_ready') {
      return `Данные еще не готовы за: ${body.detail.missing_dates.join(', ')}. Выберите другой период.`;
    }
    if (typeof body.detail === 'string') return body.detail;
  } catch (_) { /* Показываем понятное сообщение и для ответа прокси без JSON. */ }
  return `Не удалось получить отчет (код ${response.status}). Попробуйте позже.`;
}

export default function ReportPage() {
  const [session, setSession] = useState<Session | null>(null);
  const [initialized, setInitialized] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [available, setAvailable] = useState<string[]>([]);
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const response = await fetch('/auth/session', { credentials: 'same-origin' });
        if (response.status === 401) return;
        if (!response.ok) throw new Error(await errorMessage(response));
        const current: Session = await response.json();
        if (!active) return;
        setSession(current);
        if (current.can_report) {
          const coverage = await fetch('/reports/availability', { credentials: 'same-origin' });
          if (!coverage.ok) throw new Error(await errorMessage(coverage));
          const dates: string[] = (await coverage.json()).available_dates;
          if (!active) return;
          setAvailable(dates);
          setStart(dates[0] || '');
          setEnd(dates[0] || '');
        }
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : 'Не удалось загрузить приложение');
      } finally {
        if (active) setInitialized(true);
      }
    }
    void load();
    return () => { active = false; };
  }, []);

  async function downloadReport() {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const params = new URLSearchParams({ start_date: start, end_date: end, format: 'csv' });
      const response = await fetch(`/reports?${params}`, { credentials: 'same-origin' });
      if (response.status === 401) setSession(null);
      if (!response.ok) throw new Error(await errorMessage(response));
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a');
      link.href = url;
      link.download = `bionicpro_${start}_${end}.csv`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setNotice('Отчет скачан. Его можно открыть в приложении для работы с таблицами.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось скачать отчет');
    } finally {
      setBusy(false);
    }
  }

  async function logout() {
    if (!session) return;
    setBusy(true);
    setError('');
    try {
      const response = await fetch('/auth/logout', {
        method: 'POST', credentials: 'same-origin', headers: { 'X-CSRF-Token': session.csrf_token },
      });
      if (!response.ok && response.status !== 401) throw new Error(await errorMessage(response));
      setSession(null);
      setAvailable([]);
      setNotice('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось выйти');
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <section className="report-card" aria-labelledby="title">
        <p className="brand">BionicPRO</p>
        <h1 id="title">Отчет о работе протеза</h1>
        {!initialized ? <p role="status">Загружаем данные...</p> : !session ? (
          <>
            <p>Войдите в личный кабинет, чтобы скачать данные о своих протезах.</p>
            <a className="button" href="/auth/login">Войти</a>
          </>
        ) : (
          <>
            <div className="account">
              <span>Вы вошли как {session.username}</span>
              <button className="secondary" onClick={logout} disabled={busy}>Выйти</button>
            </div>
            {!session.can_report ? <p>Для этой учетной записи отчеты недоступны.</p> : (
              <>
                <p>В отчете собраны движения, время отклика и заряд батареи по каждому вашему протезу.</p>
                {available.length === 0 ? (
                  <p>Отчеты пока не подготовлены. Попробуйте позже.</p>
                ) : (
                  <form onSubmit={(event) => { event.preventDefault(); void downloadReport(); }}>
                    <p className="hint">Последний подготовленный день: {available[0]}. Даты и события указаны по UTC.</p>
                    <div className="dates">
                      <label>Начало периода
                        <input type="date" value={start} required min={available[available.length - 1]}
                          max={available[0]} onChange={(event) => setStart(event.target.value)} />
                      </label>
                      <label>Конец периода
                        <input type="date" value={end} required min={start}
                          max={available[0]} onChange={(event) => setEnd(event.target.value)} />
                      </label>
                    </div>
                    <p className="hint">Можно выбрать до 93 дней. Если за часть периода данные еще не готовы, мы сообщим об этом.</p>
                    <button className="button" type="submit" disabled={busy || !start || !end}>
                      {busy ? 'Подготавливаем файл...' : 'Скачать отчет CSV'}
                    </button>
                  </form>
                )}
              </>
            )}
          </>
        )}
        {error && <p className="error" role="alert">{error}</p>}
        {notice && <p className="notice" role="status">{notice}</p>}
      </section>
    </main>
  );
}
