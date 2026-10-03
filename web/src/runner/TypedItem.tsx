import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { KeystrokeLogger } from '../keystrokes';
import type { Lang } from '../i18n';
import type { Item, Keystroke, Task, Timing } from '../types';
import { ctestSegments, keyAnswer, shuffledOrder } from './machine';
import { useTimer } from './useTimer';

export interface TypedAnswer { value: string; event: 'submit' | 'answer'; keystrokes?: Keystroke[] }

interface Props {
  task: Task;
  item: Item;
  timing: Timing;
  lang: Lang;
  sessionId: string;
  busy: boolean;
  onSubmit: (a: TypedAnswer) => void;
}

/**
 * The response screen for every typed task type. Owns its input state, the keystroke log, the
 * keyboard shortcuts and the deadline; the runner only receives the answer. Mount it with a key
 * per item so it starts clean each time.
 */
export default function TypedItem({ task, item, timing, lang, sessionId, busy, onSubmit }: Props) {
  const { t } = useTranslation();
  const textRef = useRef<HTMLTextAreaElement | null>(null);
  const keys = useRef(new KeystrokeLogger());
  const [rating, setRating] = useState(() => (item.scale ? Math.round((item.scale.min + item.scale.max) / 2) : 0));
  const [blanks, setBlanks] = useState<string[]>(() => (task.type === 'c_test' ? ctestSegments(item.text ?? '').filter((s) => s.blank).map(() => '') : []));
  const order = useMemo(() => (item.options ? shuffledOrder(item.options.length, `${sessionId}:${item.id}`) : []), [item, sessionId]);

  // The deadline fires from a timer, so it reads the latest input through a ref.
  const submitRef = useRef<() => void>(() => undefined);
  useEffect(() => { submitRef.current = submitNow; });
  function submitNow() {
    if (busy) return;
    switch (task.type) {
      case 'rating': return onSubmit({ value: String(rating), event: 'submit' });
      case 'c_test': return onSubmit({ value: blanks.join('\u241f'), event: 'submit' });
      case 'reading_passage': return onSubmit({ value: '', event: 'submit' });
      case 'multiple_choice': case 'axb': case 'lexical_decision': return; // one-tap tasks have no deadline value
      default: return onSubmit({ value: textRef.current?.value ?? '', event: 'submit', keystrokes: keys.current.events });
    }
  }
  const submit = () => submitNow();
  const timer = useTimer(timing.respond_s, true, () => submitRef.current());
  const left = Math.ceil(timer.left);

  useEffect(() => {
    const el = textRef.current;
    const log = keys.current;
    if (el) { log.attach(el); el.focus(); }
    return () => log.detach();
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const a = keyAnswer(task, e.key, order);
      if (a && !busy) onSubmit(a);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [task, order, busy, onSubmit]);

  const choose = (value: string, event: 'submit' | 'answer') => { if (!busy) onSubmit({ value, event }); };

  switch (task.type) {
    case 'multiple_choice':
      return (
        <div className="card stack">
          {task.text && <p data-testid="task-text" style={{ whiteSpace: 'pre-wrap' }}>{task.text}</p>}
          <p className="big" data-testid="item-text" dangerouslySetInnerHTML={{ __html: item.text ?? '' }} />
          <div className="muted">{t('runner.choose')}</div>
          <div className="stack">
            {order.map((orig, pos) => (
              <button key={orig} onClick={() => choose(String(orig), 'submit')} disabled={busy} data-testid={`option-${orig}`} style={{ textAlign: 'left' }}>
                <strong>{pos + 1}.</strong> {item.options![orig]}
              </button>
            ))}
          </div>
        </div>
      );
    case 'reading_passage':
      return (
        <div className="card stack">
          <p data-testid="passage" style={{ whiteSpace: 'pre-wrap', fontSize: '1.1rem', lineHeight: 1.7 }}>{item.text}</p>
          <button className="primary" onClick={submit} disabled={busy} data-testid="done-reading">{t('runner.done_reading')}</button>
        </div>
      );
    case 'c_test': {
      let bi = -1;
      return (
        <div className="card stack">
          <div className="muted">{t('runner.fill_blanks')} · {t('common.seconds', { n: left })}</div>
          <p data-testid="ctest" style={{ fontSize: '1.15rem', lineHeight: 2.2 }}>
            {ctestSegments(item.text ?? '').map((seg, i) => {
              if (!seg.blank) return <span key={i}>{seg.text}</span>;
              const idx = ++bi;
              return (
                <input key={i} type="text" className="blank" value={blanks[idx] ?? ''} size={Math.max(2, seg.len ?? 3)} autoComplete="off" spellCheck={false} data-testid={`blank-${idx}`}
                  onChange={(e) => setBlanks((b) => { const n = [...b]; n[idx] = e.target.value; return n; })} />
              );
            })}
          </p>
          <button className="primary" onClick={submit} disabled={busy} data-testid="done-typing">{t('runner.done_typing')}</button>
        </div>
      );
    }
    case 'axb':
      return (
        <div className="card stack" style={{ textAlign: 'center' }}>
          <p className="big" data-testid="axb-question">{t('runner.axb_question')}</p>
          <div className="row" style={{ justifyContent: 'center', gap: 32 }}>
            <button onClick={() => choose('A', 'answer')} disabled={busy} data-testid="axb-a" className="choice">{t('runner.a')} <span className="muted">(F)</span></button>
            <button onClick={() => choose('B', 'answer')} disabled={busy} data-testid="axb-b" className="choice">{t('runner.b')} <span className="muted">(J)</span></button>
          </div>
        </div>
      );
    case 'lexical_decision':
      return (
        <div className="card stack" style={{ textAlign: 'center' }}>
          <div className="muted">{t('runner.is_word')}{item.target?.practice ? ` · ${t('runner.practice')}` : ''}</div>
          <p className="countdown" data-testid="lexical-item" style={{ letterSpacing: '0.04em' }}>{item.text}</p>
          <div className="row" style={{ justifyContent: 'center', gap: 32 }}>
            <button onClick={() => choose('no', 'answer')} disabled={busy} data-testid="lexical-no" className="choice">{t('runner.no')} <span className="muted">(F)</span></button>
            <button className="primary choice" onClick={() => choose('yes', 'answer')} disabled={busy} data-testid="lexical-yes">{t('runner.yes')} <span style={{ opacity: 0.7 }}>(J)</span></button>
          </div>
        </div>
      );
    case 'rating':
      return (
        <div className="card stack">
          <p className="big" data-testid="item-prompt">{item.prompt?.[lang]}</p>
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <span className="muted">{item.scale?.labels[String(item.scale.min)]?.[lang] ?? item.scale?.min}</span>
            <strong data-testid="rating-value">{rating}</strong>
            <span className="muted">{item.scale?.labels[String(item.scale.max)]?.[lang] ?? item.scale?.max}</span>
          </div>
          <input type="range" min={item.scale?.min} max={item.scale?.max} step={1} value={rating} onChange={(e) => setRating(Number(e.target.value))} data-testid="rating-input" />
          <button className="primary" onClick={submit} disabled={busy} data-testid="done-typing">{t('runner.next')}</button>
        </div>
      );
    default: // typed_response, dictation, copy_typing
      return (
        <div className="card stack">
          {task.type === 'copy_typing' && <><div className="muted">{t('runner.copy_this')}</div><p className="big" data-testid="copy-text" style={{ userSelect: 'none' }}>{item.text}</p></>}
          {item.prompt && <p className="big" data-testid="item-prompt">{item.prompt[lang]}</p>}
          {task.type === 'dictation' && <p className="big" data-testid="item-prompt">{t('runner.type_what_you_heard')}</p>}
          <div className="muted">{t('common.seconds', { n: left })}</div>
          <textarea ref={textRef} placeholder={t('runner.type_here')} data-testid="typed-input" spellCheck={false} autoCorrect="off" autoComplete="off" lang={item.target?.language === 'ko' ? 'ko' : 'en'} onPaste={(e) => e.preventDefault()} />
          <button className="primary" onClick={submit} disabled={busy} data-testid="done-typing">{t('runner.done_typing')}</button>
        </div>
      );
  }
}
