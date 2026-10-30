import { autocompletion, type CompletionContext } from "@codemirror/autocomplete";
import { StreamLanguage } from "@codemirror/language";
import { groovy } from "@codemirror/legacy-modes/mode/groovy";
import { forceLinting, linter, lintGutter, type Diagnostic } from "@codemirror/lint";
import { EditorState } from "@codemirror/state";
import { EditorView, keymap } from "@codemirror/view";
import { basicSetup } from "codemirror";
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import { GROOVY_API } from "../groovyApi";

export interface CodeError { line: number; col?: number; message: string }
export interface CodeEditorHandle { gotoLine: (line: number) => void }

function completions(ctx: CompletionContext) {
  const word = ctx.matchBefore(/[\w.]+/);
  if (!word || (word.from === word.to && !ctx.explicit)) return null;
  return {
    from: word.from,
    options: GROOVY_API.map((e) => ({ label: e.label, detail: e.detail, info: e.info || undefined, type: "function" })),
  };
}

/** Editor de código Groovy (CodeMirror 6): realce, autocompletar da API, erros por linha e Ctrl+S. */
export const CodeEditor = forwardRef<CodeEditorHandle, {
  value: string; onChange: (v: string) => void; errors: CodeError[]; onSave?: () => void; readOnly?: boolean;
}>(function CodeEditor({ value, onChange, errors, onSave, readOnly }, ref) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const errorsRef = useRef<CodeError[]>(errors);
  const onChangeRef = useRef(onChange);
  const onSaveRef = useRef(onSave);
  onChangeRef.current = onChange;
  onSaveRef.current = onSave;

  useEffect(() => {
    const lint = linter((v) => {
      const out: Diagnostic[] = [];
      for (const e of errorsRef.current) {
        const n = Math.min(Math.max(e.line || 1, 1), v.state.doc.lines);
        const line = v.state.doc.line(n);
        out.push({ from: line.from, to: line.to, severity: "error", message: e.message });
      }
      return out;
    }, { delay: 0 });
    view.current = new EditorView({
      parent: host.current!,
      state: EditorState.create({
        doc: value,
        extensions: [
          basicSetup,
          StreamLanguage.define(groovy),
          autocompletion({ override: [completions] }),
          lint, lintGutter(),
          keymap.of([{ key: "Mod-s", preventDefault: true, run: () => { onSaveRef.current?.(); return true; } }]),
          EditorState.readOnly.of(!!readOnly),
          EditorView.updateListener.of((u) => { if (u.docChanged) onChangeRef.current(u.state.doc.toString()); }),
          EditorView.theme({ "&": { fontSize: "13px", border: "1px solid var(--border)", borderRadius: "6px" },
                             ".cm-scroller": { fontFamily: "Consolas, 'Cascadia Mono', monospace", minHeight: "420px" } }),
        ],
      }),
    });
    return () => view.current?.destroy();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // valor alterado de fora (carregar versão, conversão): substitui o documento
  useEffect(() => {
    const v = view.current;
    if (v && v.state.doc.toString() !== value) {
      v.dispatch({ changes: { from: 0, to: v.state.doc.length, insert: value } });
    }
  }, [value]);

  // erros novos: força o linter a correr outra vez
  useEffect(() => {
    errorsRef.current = errors;
    if (view.current) forceLinting(view.current);
  }, [errors]);

  useImperativeHandle(ref, () => ({
    gotoLine(line: number) {
      const v = view.current;
      if (!v) return;
      const l = v.state.doc.line(Math.min(Math.max(line, 1), v.state.doc.lines));
      v.dispatch({ selection: { anchor: l.from, head: l.to }, scrollIntoView: true });
      v.focus();
    },
  }));

  return <div ref={host} className="code-editor" />;
});
