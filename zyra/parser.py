import re
from zyra.lexer import Lexer, Token
from zyra.ast import *

class ParserError(Exception):
    def __init__(self, message, token: Token, file: str = "unknown"):
        super().__init__(message)
        self.message = message
        self.token = token
        self.line = token.line
        self.column = token.column
        self.file = file

    def __str__(self):
        return f"ParserError at {self.file}:{self.line}:{self.column}: {self.message}"

class Parser:
    def __init__(self, tokens: list[Token], file: str = "unknown"):
        self.tokens = tokens
        self.pos = 0
        self.file = file

    def peek(self, offset=0) -> Token:
        if self.pos + offset < len(self.tokens):
            return self.tokens[self.pos + offset]
        return self.tokens[-1]

    def consume(self, expected_type: str = None) -> Token:
        token = self.peek()
        if expected_type and token.type != expected_type:
            raise ParserError(f"Expected {expected_type}, got {token.type}", token, self.file)
        self.pos += 1
        return token

    def consume_identifier(self) -> Token:
        token = self.peek()
        if token.type == 'ID' or token.type in Lexer.keywords_upper():
            self.pos += 1
            return token
        raise ParserError(f"Expected identifier or keyword, got {token.type}", token, self.file)

    def parse_dotted_path(self) -> str:
        parts = [self.consume_identifier().value]
        while self.peek().type == 'DOT':
            self.consume('DOT')
            parts.append(self.consume_identifier().value)
        return ".".join(parts)

    def unescape_string(self, s: str) -> str:
        return s.replace('\\n', '\n').replace('\\t', '\t').replace('\\r', '\r').replace('\\\\', '\\').replace('\\"', '"')

    def parse_string_literal(self, value: str, line: int, col: int) -> Any:
        value = self.unescape_string(value)
        # Optimization: if no interpolation indicator, return simple literal
        if '${' not in value:
            return StringLiteral(value)
            
        parts = []
        current_text = ""
        i = 0
        
        while i < len(value):
            # Check for ${ indicating start of evaluation
            if i + 1 < len(value) and value[i] == '$' and value[i+1] == '{':
                # 1. Flush any pending literal text
                if current_text:
                    parts.append(StringLiteral(current_text))
                    current_text = ""
                
                # 2. Extract expression with nested brace support
                i += 2
                start_expr = i
                brace_level = 1
                while i < len(value) and brace_level > 0:
                    if value[i] == '{':
                        brace_level += 1
                    elif value[i] == '}':
                        brace_level -= 1
                    i += 1
                
                if brace_level > 0:
                    raise ParserError("Unterminated interpolation block", Token('STRING', value, line, col), self.file)
                
                expr_str = value[start_expr:i-1].strip()
                
                # 3. Parse the expression recursively
                if expr_str:
                    try:
                        inner_lexer = Lexer(expr_str)
                        inner_tokens = inner_lexer.tokenize()
                        # Remove EOF
                        if inner_tokens and inner_tokens[-1].type == 'EOF':
                            inner_tokens.pop()
                            
                        inner_parser = Parser(inner_tokens, file=self.file)
                        parts.append(inner_parser.parse_expression())
                    except Exception as e:
                        raise ParserError(f"Syntax error in interpolation: {expr_str}", Token('STRING', value, line, col), self.file)
                continue
            
            # Standard character handling (including {text} without $)
            current_text += value[i]
            i += 1
            
        # Flush remaining text
        if current_text:
            parts.append(StringLiteral(current_text))
            
        return StringTemplate(parts)

    def parse_function_call(self, target: Any) -> FunctionCall:
        line, col = self.peek().line, self.peek().column
        self.consume('LPAREN')
        args = []
        kwargs = {}
        while self.peek().type != 'RPAREN' and self.peek().type != 'EOF':
            # Check for named argument: ID = expr
            is_kwarg = (self.peek().type == 'ID' or self.peek().type in Lexer.keywords_upper()) and self.peek(1).type == 'EQUALS'
            if is_kwarg:
                name = self.consume_identifier().value
                self.consume('EQUALS')
                val = self.parse_expression()
                kwargs[name] = val
            else:
                if kwargs:
                    raise ParserError("Positional argument follows keyword argument", self.peek(), self.file)
                args.append(self.parse_expression())
            
            if self.peek().type == 'COMMA':
                self.consume('COMMA')
        self.consume('RPAREN')
        node = FunctionCall(target, args, kwargs)
        node.line, node.column, node.file = line, col, self.file
        return node

    def parse_value(self) -> Any:
        token = self.peek()
        line, col = token.line, token.column
        node: Any = None
        
        if token.type == 'STRING':
            self.consume('STRING')
            node = self.parse_string_literal(token.value, token.line, token.column)
        elif token.type == 'NUMBER':
            node = NumberLiteral(self.consume().value)
        elif token.type == 'ID' or token.type in Lexer.keywords_upper():
            tok = self.consume_identifier()
            if tok.type == 'NULL':
                node = NullLiteral()
            else:
                node = Identifier(tok.value)
        elif token.type == 'LPAREN':
            self.consume('LPAREN')
            node = self.parse_expression()
            self.consume('RPAREN')
        elif token.type == 'LBRACKET':
            self.consume('LBRACKET')
            elements = []
            while self.peek().type != 'RBRACKET' and self.peek().type != 'EOF':
                # Support named arguments in lists: [a, b=c]
                if self.peek().type == 'ID' and self.peek(1).type == 'EQUALS' and self.peek(1).value == '=':
                    name_tok = self.consume('ID')
                    self.consume('EQUALS')
                    val = self.parse_expression()
                    node = NamedArg(name_tok.value, val)
                    node.line, node.column, node.file = name_tok.line, name_tok.column, self.file
                    elements.append(node)
                else:
                    elements.append(self.parse_expression())
                
                if self.peek().type == 'COMMA':
                    self.consume('COMMA')
            self.consume('RBRACKET')
            node = ListLiteral(elements)
        else:
            raise ParserError(f"Expected value, got {token.type}", token)

        node.line, node.column, node.file = line, col, self.file

        # Chained access/calls: a.b.c()
        while True:
            t = self.peek()
            l, c = t.line, t.column
            if t.type == 'DOT':
                self.consume('DOT')
                member = self.consume_identifier().value
                node = MemberAccess(node, member)
                node.line, node.column, node.file = l, c, self.file
            elif t.type == 'LPAREN':
                node = self.parse_function_call(node)
            else:
                break
        return node

    def parse_expression(self) -> Any:
        return self.parse_logic()

    def parse_logic(self) -> Any:
        left = self.parse_comparison()
        while self.peek().type in ('AND', 'OR'):
            op = self.consume().value.lower()
            right = self.parse_comparison()
            left = LogicExpr(left, op, right)
        return left

    def parse_comparison(self) -> Any:
        left = self.parse_binary()
        if self.peek().type in ('OPERATOR', 'EQUALS', 'IN'):
            op_tok = self.consume()
            op = op_tok.value if op_tok.type != 'IN' else 'in'
            right = self.parse_binary()
            node = ComparisonExpr(left, op, right)
            node.line, node.column, node.file = op_tok.line, op_tok.column, self.file
            return node
        return left

    def parse_binary(self) -> Any:
        left = self.parse_term()
        while self.peek().type == 'OPERATOR' and self.peek().value in ('+', '-'):
            op = self.consume().value
            right = self.parse_term()
            left = BinaryExpr(left, op, right)
        return left

    def parse_term(self) -> Any:
        left = self.parse_unary()
        while self.peek().type == 'OPERATOR' and self.peek().value in ('*', '/'):
            op = self.consume().value
            right = self.parse_unary()
            left = BinaryExpr(left, op, right)
        return left

    def parse_unary(self) -> Any:
        if self.peek().type == 'NOT' or (self.peek().type == 'OPERATOR' and self.peek().value == '-'):
            op = self.consume().value.lower()
            right = self.parse_unary()
            return UnaryExpr(op, right)
        return self.parse_value()

    def parse(self) -> Program:
        statements = []
        while self.peek().type != 'EOF':
            statements.append(self.parse_statement())
        return Program(statements)

    def parse_statement(self) -> Statement:
        token = self.peek()
        
        is_export = False
        if token.type == 'EXPORT':
            self.consume('EXPORT')
            is_export = True
            token = self.peek()

        if (token.type == 'ID' or (token.type in Lexer.keywords_upper() and token.type not in ('TOKEN', 'BOT'))) and self.peek(1).type == 'EQUALS':
            tok = self.consume_identifier()
            name = tok.value
            self.consume('EQUALS')
            val = self.parse_expression()
            return AssignmentStmt(name, val, is_export)

        if token.type == 'BOT' and self.peek(1).type == 'EQUALS':
            self.consume('BOT')
            self.consume('EQUALS')
            val = self.parse_expression()
            return BotDef(val)
        elif token.type == 'TOKEN' and self.peek(1).type == 'EQUALS':
            self.consume('TOKEN')
            self.consume('EQUALS')
            val = self.parse_expression()
            return TokenDef(val)
        elif token.type == 'IMPORT':
            self.consume('IMPORT')
            if self.peek().type == 'STRING':
                path = self.consume('STRING').value
            else:
                path = self.parse_dotted_path()
            alias = None
            if self.peek().type == 'AS':
                self.consume('AS')
                alias = self.consume_identifier().value
            return ImportDef(path, alias)
        elif token.type == 'FROM':
            self.consume('FROM')
            path_tok = self.peek()
            path = ""
            if path_tok.type == 'STRING':
                path = self.consume('STRING').value
            else:
                path = self.parse_dotted_path()
            self.consume('IMPORT')
            symbols = []
            symbols.append(self.consume_identifier().value)
            while self.peek().type == 'COMMA':
                self.consume('COMMA')
                symbols.append(self.consume_identifier().value)
            return FromImportDef(path, symbols)
        elif token.type == 'FN':
            fn_def = self.parse_function_def()
            fn_def.is_export = is_export
            return fn_def
        elif token.type == 'RETURN':
            self.consume('RETURN')
            val = self.parse_expression()
            return ReturnStmt(val)
        elif token.type == 'IF':
            return self.parse_if_chain()
        elif token.type == 'FOR':
            self.consume('FOR')
            item_name = self.consume_identifier().value
            self.consume('IN')
            iterable = self.parse_expression()
            self.consume('LBRACE')
            body = self.parse_block()
            return ForStmt(item_name, iterable, body)
        elif token.type == 'WHILE':
            self.consume('WHILE')
            cond = self.parse_expression()
            self.consume('LBRACE')
            body = self.parse_block()
            return WhileStmt(cond, body)
        elif token.type == 'ON':
            self.consume('ON')
            event_type = self.consume_identifier().value
            event_value = None
            if self.peek().type == 'STRING':
                event_value = self.consume('STRING').value
            
            if self.peek().type == 'ARROW' and self.peek().value == '=>':
                self.consume('ARROW')
                stmt = self.parse_statement()
                return EventStmt(event_type, event_value, [stmt])

            self.consume('LBRACE')
            body = self.parse_block()
            return EventStmt(event_type, event_value, body)
        elif token.type == 'COMMAND':
            self.consume('COMMAND')
            cmd = self.consume('STRING').value
            
            if self.peek().type == 'ARROW' and self.peek().value == '=>':
                self.consume('ARROW')
                stmt = self.parse_statement()
                return CommandDef(cmd, [stmt])

            self.consume('LBRACE')
            body = self.parse_block()
            return CommandDef(cmd, body)
        elif token.type == 'CALLBACK':
            self.consume('CALLBACK')
            if self.peek().type == 'STRING':
                name = self.consume('STRING').value
            else:
                name = self.consume_identifier().value
            
            if self.peek().type == 'ARROW' and self.peek().value == '=>':
                self.consume('ARROW')
                stmt = self.parse_statement()
                return CallbackDef(name, [stmt])

            self.consume('LBRACE')
            body = self.parse_block()
            return CallbackDef(name, body)
        elif token.type == 'REPLY':
            if self.peek(1).type == 'LPAREN':
                expr = self.parse_expression()
                return ExpressionStmt(expr)
            self.consume('REPLY')
            val = self.parse_expression()
            parse_mode = None
            # Check for optional mode="HTML"
            if self.peek().type == 'ID' and self.peek().value == 'mode':
                self.consume('ID')
                self.consume('EQUALS')
                parse_mode = self.consume('STRING').value
            return OutputStmt(val, 'telegram', parse_mode)
        elif token.type == 'TABLE':
            self.consume('TABLE')
            name = self.consume_identifier().value
            self.consume('LBRACE')
            fields = []
            while self.peek().type != 'RBRACE' and self.peek().type != 'EOF':
                f_name = self.consume_identifier().value
                f_type = self.consume_identifier().value
                is_primary = False
                if self.peek().type == 'PRIMARY':
                    self.consume('PRIMARY')
                    is_primary = True
                fields.append(TableField(f_name, f_type, is_primary))
            self.consume('RBRACE')
            return TableDef(name, fields)
        elif token.type == 'INSERT':
            self.consume('INSERT')
            name = self.consume_identifier().value
            self.consume('LBRACE')
            assignments = {}
            while self.peek().type != 'RBRACE' and self.peek().type != 'EOF':
                f_name = self.consume_identifier().value
                self.consume('EQUALS')
                val = self.parse_expression()
                assignments[f_name] = val
            self.consume('RBRACE')
            return InsertStmt(name, assignments)
        elif token.type == 'FIND':
            self.consume('FIND')
            table = self.consume_identifier().value
            self.consume('WHERE')
            cond = self.parse_comparison()
            return FindStmt(table, cond.left, cond.op, cond.right)
        elif token.type == 'EVERY':
            self.consume('EVERY')
            val = self.consume('NUMBER').value
            unit = self.consume_identifier().value
            self.consume('LBRACE')
            body = self.parse_block()
            return EveryDef(f"{val}{unit}", body)
        elif token.type == 'SEND':
            if self.peek(1).type == 'LPAREN':
                expr = self.parse_expression()
                return ExpressionStmt(expr)
            self.consume('SEND')
            target = self.parse_expression()
            text = self.consume('STRING').value
            return SendStmt(target, text)
        else:
            # Unify as ExpressionStmt (handles function calls, DB methods, etc)
            expr = self.parse_expression()
            
            # DB special block check: e.g. Users.insert { ... }
            if isinstance(expr, MemberAccess) and self.peek().type == 'LBRACE':
                table = expr.target.name if isinstance(expr.target, Identifier) else str(expr.target)
                method = expr.member
                self.consume('LBRACE')
                if method == 'insert':
                    assignments = {}
                    while self.peek().type != 'RBRACE' and self.peek().type != 'EOF':
                        f_name = self.consume_identifier().value
                        self.consume('EQUALS')
                        val = self.parse_expression()
                        assignments[f_name] = val
                    self.consume('RBRACE')
                    return DbInsertStmt(table, assignments)
                elif method == 'find':
                    cond = self.parse_expression() # Wait, find { id == user.id }
                    self.consume('RBRACE')
                    return DbFindStmt(table, cond)
                    
            return ExpressionStmt(expr)

    def parse_function_def(self) -> FunctionDef:
        self.consume('FN')
        name = self.consume_identifier().value
        params = []
        if self.peek().type == 'LPAREN':
            self.consume('LPAREN')
            while self.peek().type != 'RPAREN' and self.peek().type != 'EOF':
                params.append(self.consume_identifier().value)
                if self.peek().type == 'COMMA': self.consume('COMMA')
            self.consume('RPAREN')
        self.consume('LBRACE')
        body = self.parse_block()
        return FunctionDef(name, params, body)

    def parse_if_chain(self) -> IfChain:
        branches = []
        self.consume('IF')
        cond = self.parse_expression()
        
        # Support one-line if: if cond => stmt
        if self.peek().type == 'ARROW' and self.peek().value == '=>':
            self.consume('ARROW')
            stmt = self.parse_statement()
            branches.append(IfBranch(cond, [stmt]))
            return IfChain(branches)

        self.consume('LBRACE')
        body = self.parse_block()
        branches.append(IfBranch(cond, body))
        while self.peek().type == 'ELIF':
            self.consume('ELIF')
            cond = self.parse_expression()
            
            # Support one-line elif: elif cond => stmt
            if self.peek().type == 'ARROW' and self.peek().value == '=>':
                self.consume('ARROW')
                stmt = self.parse_statement()
                branches.append(IfBranch(cond, [stmt]))
                continue

            self.consume('LBRACE')
            body = self.parse_block()
            branches.append(IfBranch(cond, body))
        if self.peek().type == 'ELSE':
            self.consume('ELSE')
            
            # Support one-line else: else => stmt
            if self.peek().type == 'ARROW' and self.peek().value == '=>':
                self.consume('ARROW')
                stmt = self.parse_statement()
                branches.append(IfBranch(None, [stmt]))
                return IfChain(branches)

            self.consume('LBRACE')
            body = self.parse_block()
            branches.append(IfBranch(None, body))
        return IfChain(branches)

    def parse_block(self) -> list[Statement]:
        statements = []
        while self.peek().type != 'RBRACE' and self.peek().type != 'EOF':
            statements.append(self.parse_statement())
        self.consume('RBRACE')
        return statements
