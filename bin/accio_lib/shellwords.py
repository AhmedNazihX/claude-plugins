"""Split a shell command into simple commands the way bash reads them (protego, S-013; curfew, S-015).

Only unquoted characters make operators, so `echo "a && b"` is one command and `echo "<<E"` starts no heredoc.
Quotes (including `$'…'`) and backslashes are removed from words, and an empty `""` stays a word. `$((…))` and
`((…))` arithmetic is one word. A redirect (`>out`, `2>&1`) and its target are not words of the command; an fd
number written against it (`2>`) goes too. A heredoc's body (from the line after `<<WORD` to the line that is
exactly `WORD`, or `WORD` after leading tabs for `<<-`) and a here-string (`<<< word`) are the command's *input*,
not its words; a heredoc that never closes is not cut out, so its lines are still read as commands. Unbalanced
quotes run to the end. `#` at the start of a word starts a comment. Command substitutions (`$(…)` and backticks)
are listed by `substitutions()`, so a caller can check them as commands too; an unquoted `$(` also splits, like
a subshell.
"""
import dataclasses
import typing

OPERATORS = ("&>>", "<<<", "<<-", "&&", "||", ";;", "|&", "<<", ">>", ">&", "<&", "&>", ">|", "<>",
             ";", "&", "|", "(", ")", "<", ">", "\n")
HEREDOCS = ("<<", "<<-")
HERE_STRING = "<<<"
BLANKS = " \t\r"
DOUBLE_QUOTE_ESCAPES = '"\\$`'
ARITHMETIC_OPENERS = ("$((", "((")


@dataclasses.dataclass(frozen=True)
class Token:
    kind: str  # "word", "op", or "input" (a heredoc body)
    value: str


class Segment(typing.NamedTuple):
    words: tuple
    operator: str
    inputs: tuple  # heredoc bodies and here-strings fed to this command


def _single_quoted(command, index):
    end = command.find("'", index + 1)
    return (len(command), command[index + 1:]) if end == -1 else (end + 1, command[index + 1:end])


def _ansi_quoted(command, index):
    """`$'…'`: a backslash escapes the next character, so only an unescaped `'` ends it."""
    text, index = [], index + 2
    while index < len(command) and command[index] != "'":
        if command[index] == "\\" and index + 1 < len(command):
            index += 1
        text.append(command[index])
        index += 1
    return index + 1, "".join(text)


def _backtick_end(command, index):
    while index < len(command) and command[index] != "`":
        index += 2 if command[index] == "\\" else 1
    return min(index, len(command))


def _closing_paren(command, index, found):
    """The index of the `)` that closes a `(` just before `index` (quotes and nesting respected)."""
    depth = 1
    while index < len(command):
        char = command[index]
        if char == "\\":
            index += 2
            continue
        if char == "'":
            index = _single_quoted(command, index)[0]
            continue
        if char == '"':
            index = _double_quoted(command, index, found)[0]
            continue
        depth += {"(": 1, ")": -1}.get(char, 0)
        if depth == 0:
            return index
        index += 1
    return len(command)


def _double_quoted(command, index, found):
    """(end, text); each `$(…)` or backtick inside is added to `found`."""
    text, index = [], index + 1
    while index < len(command) and command[index] != '"':
        if command.startswith("$(", index) and not command.startswith("$((", index):
            end = _closing_paren(command, index + 2, found)
            found.append(command[index + 2:end])
            text.append(command[index:end + 1])
            index = end + 1
            continue
        if command[index] == "`":
            end = _backtick_end(command, index + 1)
            found.append(command[index + 1:end])
            text.append(command[index:end + 1])
            index = end + 1
            continue
        if command[index] == "\\" and command[index + 1:index + 2] in tuple(DOUBLE_QUOTE_ESCAPES):
            index += 1
        text.append(command[index:index + 1])
        index += 1
    return index + 1, "".join(text)


def _heredoc_bodies(command, start, delimiters):
    """(bodies, where reading resumes), or (None, start) when a heredoc never closes."""
    position, bodies = start, []
    for delimiter, strip_tabs in delimiters:
        lines = []
        while True:
            end = command.find("\n", position)
            line = command[position:] if end == -1 else command[position:end]
            following = len(command) if end == -1 else end + 1
            if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                position = following
                break
            if end == -1:
                return None, start
            lines.append(line)
            position = following
        bodies.append("\n".join(lines))
    return tuple(bodies), position


class _Reader:
    """One pass over the command; `tokens` and `substitutions` hold the result."""

    def __init__(self, command):
        self.command, self.index, self.tokens, self.substitutions = command, 0, [], []
        self.word, self.in_word = [], False
        self.heredoc_next, self.delimiters = None, []

    def flush(self):
        if self.in_word:
            value = "".join(self.word)
            if self.heredoc_next is not None:
                self.delimiters.append((value, self.heredoc_next == "<<-"))
                self.heredoc_next = None
            self.tokens.append(Token("word", value))
        self.word, self.in_word = [], False

    def add(self, text, end):
        self.word.append(text)
        self.in_word = True
        self.index = end

    def operator(self, op):
        if op[0] in "<>" and self.in_word and "".join(self.word).isdigit():
            self.word, self.in_word = [], False  # an fd number belongs to the redirect
        self.flush()
        self.index += len(op)
        if op == "\n" and self.delimiters:
            bodies, self.index = _heredoc_bodies(self.command, self.index, self.delimiters)
            self.tokens.extend(Token("input", body) for body in bodies or ())
            self.delimiters = []
        self.tokens.append(Token("op", op))
        if op in HEREDOCS:
            self.heredoc_next = op

    def quoted(self, char):
        command, index = self.command, self.index
        if char == "'":
            self.add(*reversed(_single_quoted(command, index)))
        elif char == '"':
            self.add(*reversed(_double_quoted(command, index, self.substitutions)))
        elif char == "`":
            end = _backtick_end(command, index + 1)
            self.substitutions.append(command[index + 1:end])
            self.add(command[index:end + 1], end + 1)
        elif command.startswith("$'", index):
            self.add(*reversed(_ansi_quoted(command, index)))
        else:  # arithmetic: one word, but a `$(…)` or backtick inside it still runs
            opener = next(opener for opener in ARITHMETIC_OPENERS if command.startswith(opener, index))
            end = _closing_paren(command, index + len(opener) - 1, self.substitutions)
            body = command[index + len(opener):end]
            if "$(" in body or "`" in body:
                self.substitutions.append(body)
            self.add(command[index:end + 1], end + 1)

    def step(self):
        command, index = self.command, self.index
        char = command[index]
        if char in BLANKS:
            self.flush()
            self.index += 1
        elif char == "\\":
            if command[index + 1:index + 2] == "\n":
                self.index += 2
            else:
                self.add(command[index + 1:index + 2], index + 2)
        elif char in "'\"`" or command.startswith("$'", index) or \
                any(command.startswith(opener, index) for opener in ARITHMETIC_OPENERS) and \
                (command[index] == "$" or not self.in_word):
            self.quoted(char)
        elif char == "#" and not self.in_word:
            end = command.find("\n", index)
            self.index = len(command) if end == -1 else end
        else:
            op = next((op for op in OPERATORS if command.startswith(op, index)), None)
            if op:
                self.operator(op)
            else:
                self.add(char, index + 1)


def _read(command):
    reader = _Reader(command)
    while reader.index < len(command):
        reader.step()
    reader.flush()
    return tuple(reader.tokens), tuple(reader.substitutions)


def tokens(command):
    return _read(command)[0]


def substitutions(command):
    """The commands inside `$(…)` within double quotes and inside backticks, in order."""
    return _read(command)[1]


def segments(command):
    """A Segment for each simple command: its words, the operator after it, and its input."""
    words, inputs, skip_target, here_string = [], [], False, False
    for token in tokens(command):
        if token.kind == "input":
            inputs.append(token.value)
        elif token.kind == "word":
            if skip_target:
                if here_string:
                    inputs.append(token.value)
                skip_target = here_string = False
            else:
                words.append(token.value)
        elif "<" in token.value or ">" in token.value:
            skip_target, here_string = True, token.value == HERE_STRING
        else:
            skip_target = False
            yield Segment(tuple(words), token.value, tuple(inputs))
            words, inputs = [], []
    yield Segment(tuple(words), "", tuple(inputs))
