"""Two editable Python functions, animated side by side.

Run: python -m difffinder.sorting_visualizer
Requires Python 3.9+ with Tkinter and the local difffinder package installed.
Only run code you trust: the worker process is NOT a security sandbox.
"""

import ast
import difflib
import json
import math
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import time
import traceback


# Both examples edit the list in place, which makes every change visible.
BUBBLE = '''def sort(arr):
    # Compare neighbors and move the largest value to the end.
    for end in range(len(arr) - 1, 0, -1):
        swapped = False
        for i in range(end):
            if arr[i] > arr[i + 1]:
                arr[i], arr[i + 1] = arr[i + 1], arr[i]
                swapped = True
        # An unchanged pass means the list is already sorted.
        if not swapped:
            break
    return arr
'''

SELECTION = '''def sort(arr):
    # Find the smallest remaining value for each position.
    for i in range(len(arr)):
        smallest = i
        for j in range(i + 1, len(arr)):
            if arr[j] < arr[smallest]:
                smallest = j
        if smallest != i:
            arr[i], arr[smallest] = arr[smallest], arr[i]
    return arr
'''

MAX_EVENTS = 20000
TIMEOUT_SECONDS = 8
USER_FILENAME = '<visualized_sort>'


def numeric_list(value):
    """Only finite numbers can be drawn as bars."""
    return (
        isinstance(value, list)
        and len(value) <= 100
        and all(type(x) in (int, float) and math.isfinite(x)
                and abs(x) <= 1_000_000 for x in value)
    )


def analyze(source, name):
    """Describe syntax without guessing what an algorithm means."""
    tree = ast.parse(source)
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    if not functions:
        raise ValueError('Define a regular function, for example: def sort(arr):')
    selected = next((n for n in functions if n.name == name), None)
    if selected is None:
        raise ValueError(f'No top-level function named {name!r}. Update the function-name box.')
    nodes = list(ast.walk(selected))
    return {
        'parameters': ast.unparse(selected.args),
        'for loops': sum(isinstance(n, ast.For) for n in nodes),
        'while loops': sum(isinstance(n, ast.While) for n in nodes),
        'if statements': sum(isinstance(n, ast.If) for n in nodes),
        'calls': ', '.join(sorted({ast.unparse(n.func) for n in nodes
                                   if isinstance(n, ast.Call)})) or 'none',
    }


def compare_lines(source_a, source_b):
    """Align source lines for native text widgets. No markup is generated.

    Each row contains (line_number, text, color_tag) for A and B.
    Blank placeholders keep insertions and removals aligned across panes.
    """
    lines_a, lines_b = source_a.splitlines(), source_b.splitlines()
    rows = []
    matcher = difflib.SequenceMatcher(None, lines_a, lines_b, autojunk=False)
    for operation, a_start, a_end, b_start, b_end in matcher.get_opcodes():
        count = max(a_end - a_start, b_end - b_start)
        for offset in range(count):
            a_index, b_index = a_start + offset, b_start + offset
            left = (None, '', 'gap')
            right = (None, '', 'gap')
            if a_index < a_end:
                tag = 'equal' if operation == 'equal' else 'removed' if operation == 'delete' else 'changed'
                left = (a_index + 1, lines_a[a_index], tag)
            if b_index < b_end:
                tag = 'equal' if operation == 'equal' else 'added' if operation == 'insert' else 'changed'
                right = (b_index + 1, lines_b[b_index], tag)
            rows.append((left, right))
    return rows


# ============================================================
# RECORDING ENGINE
# Runs in a separate process so slow code won't freeze the UI.
# sys.settrace observes Python lines; it does not rewrite your code.
# ============================================================

def record(source, name, values):
    analysis = analyze(source, name)
    events = []
    state = {'root': None, 'argument': None, 'lines': 0, 'changes': 0}
    deadline = time.monotonic() + TIMEOUT_SECONDS - 1
    data = list(values)
    namespace = {'__name__': '__visualized_code__'}

    def append_event(line, event_name, frame=None, explicit=None):
        # Watch the selected function's first argument, even inside helpers.
        # If it is rebound to another list, follow the new list.
        root = state['root']
        watched = root.f_locals.get(state['argument'], data) if root else data
        if explicit is not None:
            watched = explicit
        if not numeric_list(watched):
            raise ValueError('The watched argument must remain a list of up to 100 finite numbers.')
        snapshot = list(watched)
        previous = events[-1]['values'] if events else snapshot
        changed = [i for i, value in enumerate(snapshot)
                   if i >= len(previous) or previous[i] != value]
        if snapshot != previous:
            state['changes'] += 1
        # Show simple local values such as i, j, end and smallest.
        local_values = {}
        if frame is not None:
            for key, value in frame.f_locals.items():
                if type(value) in (int, float, bool, str) and len(repr(value)) < 60:
                    local_values[key] = repr(value)
                if len(local_values) >= 8:
                    break
        events.append({'values': snapshot, 'line': line, 'event': event_name,
                       'changed': changed, 'locals': local_values})

    def tracer(frame, event, argument):
        if time.monotonic() > deadline:
            raise TimeoutError('Recording took too long. Try a smaller input.')
        if frame.f_code.co_filename != USER_FILENAME:
            return None
        if event == 'call' and state['root'] is None and frame.f_code is target.__code__:
            state['root'] = frame
            state['argument'] = frame.f_code.co_varnames[0]
        if event == 'line':
            state['lines'] += 1
            if state['lines'] > MAX_EVENTS:
                raise RuntimeError(f'More than {MAX_EVENTS:,} Python line events. Try fewer numbers.')
            # Line events happen BEFORE the highlighted line executes.
            append_event(frame.f_lineno, 'Next line', frame)
        return tracer

    try:
        # User code executes with normal Python permissions in this worker.
        # The parent also enforces a timeout, including top-level code here.
        exec(compile(source, USER_FILENAME, 'exec'), namespace)
        target = namespace.get(name)
        if not callable(target) or not hasattr(target, '__code__'):
            raise ValueError('The selected name must refer to a Python function.')
        append_event(None, 'Initial input')
        sys.settrace(tracer)
        try:
            result = target(data)
        finally:
            sys.settrace(None)
        # Support either sorting in place (return None) or returning a list.
        output = data if result is None else result
        if not numeric_list(output):
            raise ValueError('Return a numeric list, or modify the input list and return None.')
        append_event(None, 'Finished', explicit=output)
        return {'events': events, 'analysis': analysis, 'lines': state['lines'],
                'changes': state['changes'], 'output': list(output),
                'sorted': output == sorted(values), 'error': None}
    except BaseException:
        sys.settrace(None)
        return {'events': events, 'analysis': analysis, 'lines': state['lines'],
                'changes': state['changes'], 'error': traceback.format_exc(limit=5)}
    finally:
        # Drop references to frames after recording.
        state['root'] = None


def compare_sources(snapshots, values):
    """Compare the selected functions without changing animation semantics."""
    import linecache
    from difffinder import compare_traces

    functions = []
    filenames = []
    try:
        for index, (source, name) in enumerate(snapshots):
            analyze(source, name)
            filename = f'<difffinder_visualizer_{index}>'
            filenames.append(filename)
            linecache.cache[filename] = (len(source), None, source.splitlines(True), filename)
            namespace = {'__name__': '__visualized_code__'}
            exec(compile(source, filename, 'exec'), namespace)
            functions.append(namespace[name])
        result = compare_traces(*functions, args=(list(values),), probe=False, max_steps=MAX_EVENTS)
        return {'report': str(result), 'same': result.same}
    finally:
        for filename in filenames:
            linecache.cache.pop(filename, None)


def worker(request_path, response_path):
    """Read a job and write a result; printing in user code stays out of the UI."""
    try:
        request = json.loads(Path(request_path).read_text(encoding='utf-8'))
        if 'snapshots' in request:
            response = compare_sources(request['snapshots'], request['values'])
        else:
            response = record(request['source'], request['name'], request['values'])
    except BaseException:
        response = {'error': traceback.format_exc(limit=5), 'events': []}
    Path(response_path).write_text(json.dumps(response), encoding='utf-8')


# ============================================================
# DESKTOP UI
# Tkinter is imported only here so the recorder can run headlessly.
# ============================================================

def launch_app():
    import tkinter as tk
    from tkinter import messagebox, ttk
    from tkinter.scrolledtext import ScrolledText

    class DiffPanel(ttk.Frame):
        """A read-only, synchronized code comparison inside the main window."""

        def __init__(self, parent):
            super().__init__(parent, padding=8)
            ttk.Label(self, text='Code differences', font=('', 16, 'bold')).pack(anchor='w')
            ttk.Label(self, text='Red: removed from A   •   Green: added in B   •   Yellow: changed lines'
                      '\nCompares the current code boxes. Return to “Code & animation” to edit them.').pack(anchor='w', pady=6)
            self.description = tk.StringVar()
            ttk.Label(self, textvariable=self.description).pack(anchor='w', pady=(0, 8))
            grid = ttk.Frame(self)
            grid.pack(fill='both', expand=True)
            grid.rowconfigure(1, weight=1)
            for column in (0, 1):
                grid.columnconfigure(column, weight=1, uniform='code')
                ttk.Label(grid, text=f"Function {'A' if column == 0 else 'B'}",
                          font=('', 12, 'bold')).grid(row=0, column=column, sticky='w', pady=5)
            self.texts = []
            self.syncing = False
            self.scrollbar = ttk.Scrollbar(grid, orient='vertical', command=self.scroll_both)
            self.scrollbar.grid(row=1, column=2, sticky='ns')
            for column in (0, 1):
                text = tk.Text(grid, wrap='none', font=('Courier', 12), width=40,
                               background='#f8fafc', foreground='#111827',
                               selectbackground='#bfdbfe', selectforeground='#111827',
                               borderwidth=1, relief='solid', padx=6, pady=6)
                text.grid(row=1, column=column, sticky='nsew', padx=(0, 5))
                horizontal = ttk.Scrollbar(grid, orient='horizontal', command=text.xview)
                horizontal.grid(row=2, column=column, sticky='ew', padx=(0, 5))
                text.configure(xscrollcommand=horizontal.set)
                for tag, color in [('removed', '#fee2e2'), ('added', '#dcfce7'),
                                   ('changed', '#fef3c7'), ('gap', '#e2e8f0')]:
                    text.tag_configure(tag, background=color)
                text.configure(state='disabled',
                               yscrollcommand=lambda first, last, index=column: self.sync_scroll(index, first, last))
                self.texts.append(text)

        def scroll_both(self, *arguments):
            # The shared scrollbar moves both panes by the same amount.
            for text in self.texts:
                text.yview(*arguments)

        def sync_scroll(self, index, first, last):
            # Also synchronize mouse-wheel and keyboard scrolling in either pane.
            if self.syncing or len(self.texts) != 2:
                return
            self.syncing = True
            try:
                self.scrollbar.set(first, last)
                other = self.texts[1 - index]
                if abs(other.yview()[0] - float(first)) > 0.000001:
                    other.yview_moveto(first)
            finally:
                self.syncing = False

        def refresh(self, source_a, source_b):
            rows = compare_lines(source_a, source_b)
            affected = [0, 0]
            self.syncing = True
            try:
                for side, text in enumerate(self.texts):
                    text.configure(state='normal')
                    text.delete('1.0', 'end')
                    for row in rows:
                        number, content, tag = row[side]
                        # Line numbers refer to the ORIGINAL input, not aligned rows.
                        prefix = f'{number:4}  ' if number is not None else '      '
                        text.insert('end', prefix + content + '\n', tag)
                        if tag in ('removed', 'added', 'changed'):
                            affected[side] += 1
                    text.configure(state='disabled')
                    text.yview_moveto(0)
                    text.xview_moveto(0)
            finally:
                self.syncing = False
            if not any(affected):
                self.description.set('No line differences found.')
            else:
                self.description.set(f'A: {affected[0]} affected lines   •   B: {affected[1]} affected lines')

    class SortPanel(ttk.Frame):
        def __init__(self, parent, title, source, color):
            super().__init__(parent, padding=8)
            self.color = color
            self.result = None
            self.last_event = None
            self.position = 0
            self.visible_events = []
            self.name = tk.StringVar(value='sort')
            ttk.Label(self, text=title, font=('', 16, 'bold')).pack(anchor='w')
            name_row = ttk.Frame(self)
            name_row.pack(fill='x', pady=5)
            ttk.Label(name_row, text='Function to run:').pack(side='left')
            ttk.Entry(name_row, textvariable=self.name, width=18).pack(side='left', padx=8)
            self.editor = ScrolledText(self, height=15, width=48, undo=True,
                                       font=('Courier', 12), wrap='none')
            self.editor.pack(fill='both', expand=True)
            self.editor.insert('1.0', source)
            self.editor.tag_configure('current', background='#fff0a6', foreground='#111111')
            # Insert four spaces when Tab is pressed in the code editor.
            self.editor.bind('<Tab>', self.indent)
            self.canvas = tk.Canvas(self, height=205, bg='#111827', highlightthickness=0)
            self.canvas.pack(fill='x', pady=(10, 5))
            self.canvas.bind('<Configure>', lambda event: self.redraw())
            self.caption = tk.StringVar(value='Paste Python code above, then click Compare & Record.')
            ttk.Label(self, textvariable=self.caption, wraplength=550).pack(anchor='w')
            self.locals_text = tk.StringVar(value=' ')
            ttk.Label(self, textvariable=self.locals_text, wraplength=550).pack(anchor='w')

        def indent(self, event):
            self.editor.insert('insert', '    ')
            return 'break'

        def source(self):
            return self.editor.get('1.0', 'end-1c')

        def reset(self, values):
            self.result = None
            self.visible_events = []
            self.position = 0
            self.editor.tag_remove('current', '1.0', 'end')
            self.last_event = {'values': values, 'changed': [], 'event': 'Initial input'}
            self.redraw()

        def set_filter(self, changes_only):
            events = self.result.get('events', []) if self.result else []
            # Keep start/end and any event where the list actually changed.
            self.visible_events = [e for i, e in enumerate(events)
                                   if not changes_only or i == 0 or i == len(events) - 1
                                   or e['values'] != events[i - 1]['values']]
            self.position = 0
            if self.visible_events:
                self.show(0)

        def show(self, position):
            self.position = min(position, len(self.visible_events) - 1)
            event = self.visible_events[self.position]
            self.last_event = event
            self.editor.tag_remove('current', '1.0', 'end')
            line = event.get('line')
            if line:
                self.editor.tag_add('current', f'{line}.0', f'{line}.end')
                self.editor.see(f'{line}.0')
            suffix = f' — next line: {line}' if line else ''
            self.caption.set(f"Frame {self.position + 1}/{len(self.visible_events)}"
                             f" — {event['event']}{suffix}")
            self.locals_text.set('   '.join(f'{k}={v}' for k, v in event.get('locals', {}).items()) or ' ')
            self.redraw()

        def redraw(self):
            self.canvas.delete('all')
            if not self.last_event:
                return
            values = self.last_event['values']
            width = max(self.canvas.winfo_width(), 100)
            height = max(self.canvas.winfo_height(), 100)
            if not values:
                self.canvas.create_text(width / 2, height / 2, text='Empty list []', fill='white')
                return
            # Both panels use the SAME scale, including for negative values.
            low, high = app.bounds
            span = high - low or 1
            def y(value):
                return 22 + (high - value) / span * (height - 52)
            baseline = y(0)
            self.canvas.create_line(10, baseline, width - 10, baseline, fill='#64748b')
            cell = (width - 20) / len(values)
            changed = set(self.last_event.get('changed', []))
            finished = self.last_event.get('event') == 'Finished' and self.result and self.result.get('sorted')
            for index, value in enumerate(values):
                left = 10 + index * cell + 1
                right = 10 + (index + 1) * cell - 1
                fill = '#4ade80' if finished else '#fbbf24' if index in changed else self.color
                top, bottom = sorted((baseline, y(value)))
                self.canvas.create_rectangle(left, top, right, max(bottom, top + 2), fill=fill, outline='')
                if cell >= 24:
                    self.canvas.create_text((left + right) / 2, height - 13,
                                            text=f'{value:g}', fill='#e2e8f0', font=('', 9))

    class App:
        def __init__(self, root):
            self.root = root
            self.jobs = []
            self.scratch = None
            self.playing = False
            self.timer = None
            self.bounds = (0, 100)
            self.snapshots = []
            self.recorded_input = None
            root.title('DiffFinder Sorting Visualizer')
            root.geometry('1220x900')
            root.minsize(900, 700)
            root.protocol('WM_DELETE_WINDOW', self.close)
            wrapper = ttk.Frame(root, padding=12)
            wrapper.pack(fill='both', expand=True)
            ttk.Label(wrapper, text='Paste two sorting functions. Watch the same input change.',
                      font=('', 17, 'bold')).pack(anchor='w')
            ttk.Label(wrapper, text='Run only code you trust. Each function receives one list; '
                      'modify it in place or return a new list.').pack(anchor='w', pady=(4, 10))
            controls = ttk.Frame(wrapper)
            controls.pack(fill='x')
            ttk.Label(controls, text='Input numbers:').pack(side='left')
            self.input = tk.StringVar(value='42, 17, 8, 63, 29, 51, 4, 36, 22, 75, 12, 58')
            ttk.Entry(controls, textvariable=self.input).pack(side='left', fill='x', expand=True, padx=8)
            ttk.Button(controls, text='Random input', command=self.randomize).pack(side='left')
            self.record_button = ttk.Button(controls, text='Compare & Record', command=self.start)
            self.record_button.pack(side='left', padx=(8, 0))
            self.cancel_button = ttk.Button(controls, text='Cancel', command=self.cancel, state='disabled')
            self.cancel_button.pack(side='left', padx=(8, 0))
            # Both views are native Tkinter tabs in the same Python window.
            self.tabs = ttk.Notebook(wrapper)
            self.tabs.pack(fill='both', expand=True, pady=8)
            self.animation_tab = ttk.Frame(self.tabs)
            self.diff_tab = DiffPanel(self.tabs)
            self.tabs.add(self.animation_tab, text='Code & animation')
            self.tabs.add(self.diff_tab, text='Code differences')
            self.comparison_tab = ttk.Frame(self.tabs, padding=8)
            self.tabs.add(self.comparison_tab, text='DiffFinder comparison')
            ttk.Label(self.comparison_tab, text='A is the candidate; B is the reference. '
                      'Compares return values, exceptions and input mutations on this input.\n'
                      'Functions run again for this comparison; automatic input probing is off.').pack(anchor='w')
            self.comparison_text = ScrolledText(self.comparison_tab, wrap='word', font=('Courier', 12))
            self.comparison_text.pack(fill='both', expand=True, pady=8)
            self.set_comparison('Click Compare & Record to see the DiffFinder report.')
            columns = ttk.Panedwindow(self.animation_tab, orient='horizontal')
            columns.pack(fill='both', expand=True)
            self.panels = [SortPanel(columns, 'Function A', BUBBLE, '#38bdf8'),
                           SortPanel(columns, 'Function B', SELECTION, '#a78bfa')]
            for panel in self.panels:
                columns.add(panel, weight=1)
            playback = ttk.Frame(wrapper)
            playback.pack(fill='x', pady=5)
            self.play_button = ttk.Button(playback, text='Play', command=self.play)
            self.play_button.pack(side='left')
            ttk.Button(playback, text='Pause', command=self.pause).pack(side='left', padx=5)
            ttk.Button(playback, text='Step', command=self.step_once).pack(side='left')
            ttk.Button(playback, text='Restart', command=self.restart).pack(side='left', padx=5)
            self.changes_only = tk.BooleanVar(value=True)
            ttk.Checkbutton(playback, text='Only list changes', variable=self.changes_only,
                            command=self.refilter).pack(side='left', padx=8)
            ttk.Label(playback, text='Frames/sec').pack(side='left')
            self.speed = tk.DoubleVar(value=8)
            ttk.Scale(playback, from_=1, to=40, variable=self.speed, length=130).pack(side='left', padx=5)
            ttk.Button(playback, text='View code diff', command=self.show_diff).pack(side='right')
            self.status = tk.StringVar(value='Ready. Edit either code box and click Compare & Record.')
            ttk.Label(wrapper, textvariable=self.status, wraplength=1120).pack(anchor='w', pady=5)
            self.summary = ScrolledText(wrapper, height=6, wrap='word', font=('Courier', 11))
            self.summary.pack(fill='x')
            self.summary.insert('1.0', 'Yellow bars changed since the previous recorded line. '
                                'Green means the final result matches ascending sorted(input).\n'
                                'The highlighted line executes NEXT. Uncheck “Only list changes” '
                                'to step through every Python line.\n'
                                'Built-in sorted()/list.sort() execute internally, so their internal '
                                'steps are not visible. Write the sorting loop in Python for animation.')
            self.summary.configure(state='disabled')
            self.tabs.bind('<<NotebookTabChanged>>', self.tab_changed)

        def randomize(self):
            self.input.set(', '.join(map(str, random.sample(range(1, 100), 18))))

        def set_comparison(self, report):
            self.comparison_text.configure(state='normal')
            self.comparison_text.delete('1.0', 'end')
            self.comparison_text.insert('1.0', report)
            self.comparison_text.configure(state='disabled')

        def get_values(self):
            raw = self.input.get().strip()
            # Accept either 3, 1, 2 or [3, 1, 2]; never eval the input.
            values = ast.literal_eval(raw if raw.startswith('[') else '[' + raw + ']')
            if not numeric_list(values):
                raise ValueError('Enter up to 100 numbers between -1,000,000 and 1,000,000.')
            return values

        def start(self):
            self.pause()
            try:
                values = self.get_values()
                snapshots = [(p.source(), p.name.get().strip()) for p in self.panels]
                for source, name in snapshots:
                    analyze(source, name)
            except Exception as error:
                messagebox.showerror('Check your input or Python code', str(error))
                return
            self.recorded_input = self.input.get()
            self.snapshots = snapshots
            self.tabs.select(self.animation_tab)
            self.stop_jobs()
            self.scratch = tempfile.TemporaryDirectory(prefix='sort_visualizer_')
            self.bounds = (min([0] + values), max([0] + values))
            for index, panel in enumerate(self.panels):
                panel.reset(values)
                panel.caption.set('Recording…')
                # Lock the code so line highlighting matches the recorded version.
                panel.editor.configure(state='disabled')
                request = Path(self.scratch.name) / f'request_{index}.json'
                response = Path(self.scratch.name) / f'response_{index}.json'
                source, name = self.snapshots[index]
                request.write_text(json.dumps({'source': source, 'name': name, 'values': values}), encoding='utf-8')
                process = subprocess.Popen(
                    [sys.executable, str(Path(__file__).resolve()), '--worker', str(request), str(response)],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.jobs.append({'process': process, 'response': response, 'panel': panel,
                                  'started': time.monotonic()})
            self.set_comparison('Comparing recorded code…')
            request = Path(self.scratch.name) / 'comparison_request.json'
            response = Path(self.scratch.name) / 'comparison_response.json'
            request.write_text(json.dumps({'snapshots': snapshots, 'values': values}), encoding='utf-8')
            process = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), '--worker', str(request), str(response)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.jobs.append({'process': process, 'response': response, 'panel': None,
                              'started': time.monotonic()})
            self.record_button.configure(state='disabled')
            self.cancel_button.configure(state='normal')
            self.status.set('Recording both functions… Each has an 8-second limit.')
            self.root.after(80, self.poll)

        def poll(self):
            if not self.jobs:
                return
            for job in self.jobs:
                if 'result' in job:
                    continue
                process = job['process']
                if process.poll() is None and time.monotonic() - job['started'] > TIMEOUT_SECONDS:
                    process.kill()
                    process.wait()
                    job['result'] = {'events': [], 'error': 'Timed out after 8 seconds. Check for an infinite loop.'}
                elif process.poll() is not None:
                    try:
                        job['result'] = json.loads(job['response'].read_text(encoding='utf-8'))
                    except Exception:
                        job['result'] = {'events': [], 'error': 'The worker stopped without a readable result.'}
            if not all('result' in job for job in self.jobs):
                self.root.after(80, self.poll)
                return
            for job in self.jobs:
                if job['panel'] is None:
                    self.set_comparison(job['result'].get('report') or job['result'].get('error', 'No report.'))
                else:
                    job['panel'].result = job['result']
            # Include intermediate values in the shared vertical scale.
            all_values = [0] + [v for p in self.panels for e in p.result['events'] for v in e['values']]
            self.bounds = (min(all_values), max(all_values))
            self.refilter()
            self.write_summary()
            self.stop_jobs()
            self.unlock()
            self.status.set('Recording complete. Play or Step to inspect it. After editing code or input, record again.')

        def unlock(self):
            self.record_button.configure(state='normal')
            self.cancel_button.configure(state='disabled')
            for panel in self.panels:
                panel.editor.configure(state='normal')

        def write_summary(self):
            lines = []
            for label, panel in zip(('A', 'B'), self.panels):
                result = panel.result
                if result.get('error'):
                    lines.append(f"{label} ERROR:\n{result['error']}")
                    panel.caption.set('Recording error — see details below.')
                else:
                    lines.append(f"{label}: {result['lines']} Python line events; "
                                 f"{result['changes']} observed list changes; "
                                 f"ascending result: {'YES' if result['sorted'] else 'NO'}; "
                                 f"output: {result['output']}")
            a, b = [p.result for p in self.panels]
            if not a.get('error') and not b.get('error'):
                lines.append('Same output on this input: ' + ('YES' if a['output'] == b['output'] else 'NO'))
            if a.get('analysis') and b.get('analysis'):
                differences = [f"{key}: A={a['analysis'][key]}, B={b['analysis'][key]}"
                               for key in a['analysis'] if a['analysis'][key] != b['analysis'][key]]
                lines.extend(differences or ['The structural features checked are the same.'])
            lines.append('Counts describe this recording, not runtime speed or Big-O complexity. '
                         'Matching one input does not prove equivalence.')
            self.summary.configure(state='normal')
            self.summary.delete('1.0', 'end')
            self.summary.insert('1.0', '\n'.join(lines))
            self.summary.configure(state='disabled')

        def refilter(self):
            self.pause()
            for panel in self.panels:
                panel.set_filter(self.changes_only.get())

        def sources_match(self):
            return (self.recorded_input == self.input.get()
                    and self.snapshots == [(p.source(), p.name.get().strip()) for p in self.panels])

        def advance(self):
            if self.jobs or not self.sources_match():
                self.status.set('Click Compare & Record to record the current code first.')
                return False
            advanced = False
            for panel in self.panels:
                if panel.position + 1 < len(panel.visible_events):
                    panel.show(panel.position + 1)
                    advanced = True
            return advanced

        def step_once(self):
            self.pause()
            self.advance()

        def play(self):
            if self.playing or self.jobs:
                return
            if not any(p.visible_events for p in self.panels):
                self.status.set('Click Compare & Record first.')
                return
            self.tabs.select(self.animation_tab)
            self.playing = True
            self.tick()

        def tick(self):
            self.timer = None
            if self.playing and self.advance():
                self.timer = self.root.after(max(1, int(1000 / self.speed.get())), self.tick)
            else:
                self.playing = False

        def pause(self):
            self.playing = False
            if self.timer is not None:
                self.root.after_cancel(self.timer)
                self.timer = None

        def restart(self):
            self.pause()
            for panel in self.panels:
                if panel.visible_events:
                    panel.show(0)

        def show_diff(self):
            self.pause()
            self.diff_tab.refresh(*(panel.source() for panel in self.panels))
            self.tabs.select(self.diff_tab)

        def tab_changed(self, event):
            # Clicking the tab itself also refreshes the current code comparison.
            if self.tabs.select() == str(self.diff_tab):
                self.pause()
                self.diff_tab.refresh(*(panel.source() for panel in self.panels))

        def stop_jobs(self):
            for job in self.jobs:
                if job['process'].poll() is None:
                    job['process'].kill()
                    job['process'].wait()
            self.jobs = []
            if self.scratch:
                self.scratch.cleanup()
                self.scratch = None

        def cancel(self):
            self.stop_jobs()
            self.set_comparison('Comparison cancelled. Click Compare & Record to try again.')
            self.unlock()
            self.status.set('Recording cancelled. Edit the code and try again.')

        def close(self):
            self.pause()
            self.stop_jobs()
            self.root.destroy()

    root = tk.Tk()
    app = App(root)
    root.mainloop()


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == '--worker':
        worker(sys.argv[2], sys.argv[3])
    else:
        launch_app()
