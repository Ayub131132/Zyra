import os
import sys
import sqlite3
import logging
import asyncio
from typing import Any, List
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, filters, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from zyra.lexer import Lexer
from zyra.parser import Parser
from zyra.ast import *
from zyra.runtime.context import ZyraContext

logger = logging.getLogger(__name__)

class ZyraRuntimeError(Exception):
    def __init__(self, message, node=None):
        super().__init__(message)
        self.message = message
        self.node = node

    def __str__(self):
        if self.node:
            return f"Zyra Runtime Error:\nFile: {self.node.file}:{self.node.line}\nError: {self.message}"
        return f"Zyra Runtime Error: {self.message}"

class ZyraReturn(Exception):
    def __init__(self, value):
        self.value = value

class Interpreter:
    def __init__(self, parent=None):
        self.parent = parent
        self.global_env = parent.global_env if parent else {}
        self.functions = parent.functions if parent else {}
        self.exported_symbols = {} # name -> value
        self.current_node = None
        
        if parent:
            self._db_conn = None
            self._db_cursor = None
            self.ai_config = parent.ai_config
            self.app = parent.app
            self.scheduler = parent.scheduler
            self.import_cache = parent.import_cache
            self.import_stack = parent.import_stack
            self.base_dir = parent.base_dir
            self.pending_handlers = parent.pending_handlers
            self.global_parse_mode = parent.global_parse_mode
        else:
            self._db_conn = None
            self._db_cursor = None
            self.ai_config = {"provider": None, "model": None}
            self.app = None
            self.import_cache = {}
            self.import_stack = []
            self.base_dir = os.getcwd()
            self.pending_handlers = []
            self.global_parse_mode = None
            self.global_env.update({"true": True, "false": False})
            
            # Root Built-ins
            import random
            self.functions = {
                "env": lambda key: os.environ.get(str(key)),
                "len": lambda obj: len(obj) if hasattr(obj, '__len__') else 0,
                "random": lambda a, b: random.randint(int(a), int(b)),
                "sleep": lambda s: asyncio.sleep(float(s)),
                "print": lambda *args: self._print(*(str(a) for a in args)),
                "reply": self._builtin_reply,
                "send": self._builtin_send,
                "alert": self._builtin_alert,
                "delete": self._builtin_delete,
                "restrict": self._builtin_restrict,
                "approve_join": self._builtin_approve_join,
                "db_execute": self._builtin_db_execute,
                "db_fetchone": self._builtin_db_fetchone,
                "db_fetchall": self._builtin_db_fetchall,
                "dict": lambda: {},
                "set_key": lambda d, k, v: d.update({str(k): v}),
                "get_key": lambda d, k: d.get(str(k)),
                "pop_key": lambda d, k: d.pop(str(k), None),
                "get_item": lambda l, i: l[int(i)],
                "set_item": lambda l, i, v: l.__setitem__(int(i), v),
                "int": lambda x: int(x),
                "float": lambda x: float(x),
                "str": lambda x: str(x),
                "lower": lambda x: str(x).lower(),
                "replace": lambda s, old, new: str(s).replace(str(old), str(new)),
                "is_digit": lambda s: str(s).isdigit(),
                "strip": lambda s: str(s).strip()
            }
            
            tz = self._get_safe_timezone()
            self.scheduler = AsyncIOScheduler(timezone=tz)
        
    def _get_safe_timezone(self):
        from datetime import timezone
        utc_builtin = timezone.utc
        try:
            import tzlocal
            local_tz = tzlocal.get_localzone()
            if str(local_tz) == "Asia/Calcutta": return "Asia/Kolkata"
            return local_tz
        except Exception:
            return utc_builtin

    def _get_db(self):
        # Resolve from parent if available
        root = self
        while root.parent:
            root = root.parent
            
        if root._db_conn is None:
            root._db_conn = sqlite3.connect("bot.db", check_same_thread=False)
            root._db_cursor = root._db_conn.cursor()
        return root._db_conn, root._db_cursor

    async def _db_execute(self, query: str, params: tuple = ()):
        conn, cursor = self._get_db()
        def run():
            cursor.execute(query, params)
            conn.commit()
        await asyncio.to_thread(run)

    async def _db_fetchone(self, query: str, params: tuple = ()):
        _, cursor = self._get_db()
        def run():
            cursor.execute(query, params)
            return cursor.fetchone()
        return await asyncio.to_thread(run)

    async def _builtin_reply(self, text, mode=None, buttons=None, inline=None, _env=None):
        if not _env: return
        zyra_ctx = _env.get("_zyra_context")
        mode = mode or self.global_parse_mode
        
        reply_markup = None
        
        if buttons:
            # Handle reply keyboard
            # [[text1, text2]] or [text1, text2]
            keyboard = []
            for row in buttons:
                if isinstance(row, list):
                    keyboard.append([KeyboardButton(str(b)) for b in row])
                else:
                    keyboard.append([KeyboardButton(str(row))])
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
        if inline:
            # Handle inline keyboard
            # [[ [text, data], [text, url=...] ]]
            keyboard = []
            for row in inline:
                if not isinstance(row, list): continue
                
                # Check if this row is actually a single button [text, data]
                # A row can be a list of buttons, or a button itself.
                # If row[0] is a list, then row is a list of buttons.
                if len(row) > 0 and isinstance(row[0], list):
                    # List of buttons in this row
                    btn_row = []
                    for btn_data in row:
                        btn_row.append(self._make_inline_button(btn_data))
                    keyboard.append(btn_row)
                else:
                    # Single button in this row
                    keyboard.append([self._make_inline_button(row)])
            reply_markup = InlineKeyboardMarkup(keyboard)

        if zyra_ctx and zyra_ctx.message: 
            await zyra_ctx.message.reply_text(str(text), parse_mode=mode, reply_markup=reply_markup)
        elif zyra_ctx and zyra_ctx.query and zyra_ctx.query.message: 
            await zyra_ctx.query.message.reply_text(str(text), parse_mode=mode, reply_markup=reply_markup)
        else: 
            self._print(str(text))

    def _make_inline_button(self, btn_data):
        if not isinstance(btn_data, list) or len(btn_data) == 0:
            return InlineKeyboardButton(str(btn_data), callback_data=str(btn_data))
            
        text = str(btn_data[0])
        
        # Check for URL or callback data
        for item in btn_data[1:]:
            if isinstance(item, dict) and item.get("_type") == "named_arg":
                if item["name"] == "url":
                    return InlineKeyboardButton(text, url=str(item["value"]))
            else:
                return InlineKeyboardButton(text, callback_data=str(item))
                
        # Fallback to text as callback data if only text provided
        return InlineKeyboardButton(text, callback_data=text)

    async def _builtin_alert(self, text, mode=None, _env=None, **kwargs):
        if not _env: return
        zyra_ctx = _env.get("_zyra_context")
        if not zyra_ctx or not zyra_ctx.query:
            raise ZyraRuntimeError("alert() can only be used inside callback events.")
        
        show_alert = (mode == "alert")
        await zyra_ctx.query.answer(text=str(text), show_alert=show_alert, **kwargs)
        _env["_callback_answered"] = True

    async def _builtin_send(self, target, text, mode=None, inline=None, _env=None):
        mode = mode or self.global_parse_mode
        reply_markup = None
        if inline:
            keyboard = []
            for row in inline:
                if not isinstance(row, list): continue
                if len(row) > 0 and isinstance(row[0], list):
                    btn_row = []
                    for btn_data in row:
                        btn_row.append(self._make_inline_button(btn_data))
                    keyboard.append(btn_row)
                else:
                    keyboard.append([self._make_inline_button(row)])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
        await self.app.bot.send_message(chat_id=target, text=str(text), parse_mode=mode, reply_markup=reply_markup)

    async def _builtin_delete(self, _env=None):
        if not _env: return
        zyra_ctx = _env.get("_zyra_context")
        if zyra_ctx and zyra_ctx.message:
            await zyra_ctx.message.delete()
        elif zyra_ctx and zyra_ctx.query and zyra_ctx.query.message:
            await zyra_ctx.query.message.delete()

    async def _builtin_restrict(self, user_id, can_send=True, _env=None):
        if not _env: return
        zyra_ctx = _env.get("_zyra_context")
        if not zyra_ctx: return
        
        from telegram import ChatPermissions
        perms = ChatPermissions(can_send_messages=can_send)
        await self.app.bot.restrict_chat_member(chat_id=zyra_ctx.chat_id, user_id=user_id, permissions=perms)

    async def _builtin_approve_join(self, request=None, _env=None):
        if request:
            # Handle raw request object from get_key(join_requests, ...)
            await self.app.bot.approve_chat_join_request(chat_id=request.chat.id, user_id=request.from_user.id)
        else:
            if not _env: return
            zyra_ctx = _env.get("_zyra_context")
            if zyra_ctx and zyra_ctx.update and zyra_ctx.update.chat_join_request:
                req = zyra_ctx.update.chat_join_request
                await self.app.bot.approve_chat_join_request(chat_id=req.chat.id, user_id=req.from_user.id)

    async def _builtin_db_execute(self, query, params=None):
        if params is None: params = []
        if isinstance(params, list): params = tuple(params)
        await self._db_execute(query, params)

    async def _builtin_db_fetchone(self, query, params=None):
        if params is None: params = []
        if isinstance(params, list): params = tuple(params)
        _, cursor = self._get_db()
        def run():
            cursor.row_factory = sqlite3.Row
            cursor.execute(query, params)
            row = cursor.fetchone()
            return dict(row) if row else None
        return await asyncio.to_thread(run)

    async def _builtin_db_fetchall(self, query, params=None):
        if params is None: params = []
        if isinstance(params, list): params = tuple(params)
        _, cursor = self._get_db()
        def run():
            cursor.row_factory = sqlite3.Row
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        return await asyncio.to_thread(run)

    async def evaluate_member_access(self, val: MemberAccess, env: dict) -> Any:
        target = await self.evaluate_value(val.target, env)
        if target is None:
            return None
        if isinstance(target, ZyraContext):
            return target.get_member(None, val.member)
        if isinstance(target, dict):
            return target.get(val.member)
        return getattr(target, val.member, None)

    async def evaluate_value(self, val: Any, env: dict) -> Any:
        if val is None: return None
        if isinstance(val, ASTNode):
            self.current_node = val

        if isinstance(val, MemberAccess):
            return await self.evaluate_member_access(val, env)
        elif isinstance(val, NamedArg):
            return {"_type": "named_arg", "name": val.name, "value": await self.evaluate_value(val.value, env)}
        elif isinstance(val, NullLiteral):
            return None
        elif isinstance(val, Identifier):
            if val.name in env: return env[val.name]
            if val.name in self.global_env: return self.global_env[val.name]
            zyra_ctx = env.get("_zyra_context")
            if zyra_ctx and hasattr(zyra_ctx, val.name):
                return getattr(zyra_ctx, val.name)
            raise ZyraRuntimeError(f"Variable '{val.name}' is not defined", val)
        elif isinstance(val, StringLiteral):
            return val.value
        elif isinstance(val, StringTemplate):
            res = ""
            for part in val.parts:
                eval_part = await self.evaluate_value(part, env)
                res += str(eval_part)
            return res
        elif isinstance(val, NumberLiteral):
            try:
                if '.' in val.value: return float(val.value)
                return int(val.value)
            except ValueError: return val.value
        elif isinstance(val, ListLiteral):
            return [await self.evaluate_value(e, env) for e in val.elements]
        elif isinstance(val, UnaryExpr):
            return await self.evaluate_unary(val, env)
        elif isinstance(val, ComparisonExpr):
            return await self.evaluate_comparison(val, env)
        elif isinstance(val, LogicExpr):
            return await self.evaluate_logic(val, env)
        elif isinstance(val, BinaryExpr):
            return await self.evaluate_binary(val, env)
        elif isinstance(val, FunctionCall):
            return await self.call_function(val, env)
        return val

    async def evaluate_unary(self, expr: UnaryExpr, env: dict) -> Any:
        right = await self.evaluate_value(expr.right, env)
        if expr.op == "not":
            return not right
        if expr.op == "-":
            return -right
        return right

    async def evaluate_binary(self, expr: BinaryExpr, env: dict) -> Any:
        l = await self.evaluate_value(expr.left, env)
        r = await self.evaluate_value(expr.right, env)
        if expr.op == '+':
            if isinstance(l, (int, float)) and isinstance(r, (int, float)): return l + r
            return str(l) + str(r)
        if expr.op == '-': return l - r
        if expr.op == '*': return l * r
        if expr.op == '/': return l / r
        return None

    async def evaluate_comparison(self, expr: ComparisonExpr, env: dict) -> bool:
        l = await self.evaluate_value(expr.left, env)
        r = await self.evaluate_value(expr.right, env)
        op = expr.op

        # Safe numeric casting for comparisons (e.g. user.id == ADMIN)
        try:
            if isinstance(l, (int, float)) and not isinstance(r, (int, float)):
                r = type(l)(r)
            elif isinstance(r, (int, float)) and not isinstance(l, (int, float)):
                l = type(r)(l)
        except (ValueError, TypeError):
            pass

        if op in ("==", "="): return l == r
        if op == "!=": return l != r
        if op == "in":
            try:
                return l in r
            except TypeError:
                return False

        try:
            if op == ">": return l > r
            if op == "<": return l < r
            if op == ">=": return l >= r
            if op == "<=": return l <= r
        except TypeError as e:
            raise ZyraRuntimeError(f"Cannot compare {type(l).__name__} and {type(r).__name__}", expr)
        return False

    async def evaluate_logic(self, expr: LogicExpr, env: dict) -> bool:
        left_res = await self.evaluate_value(expr.left, env)
        if expr.op == "and":
            if not left_res: return False
            return await self.evaluate_value(expr.right, env)
        elif expr.op == "or":
            if left_res: return True
            return await self.evaluate_value(expr.right, env)
        return False

    async def execute_block(self, body: List[Statement], env: dict):
        self._log(f"[Zyra] Running AST block ({len(body)} statements)")
        for stmt in body:
            if os.environ.get("ZYRA_TRACE"):
                self._log(f"[Trace] Executing {type(stmt).__name__} at {stmt.file}:{stmt.line}")
            try:
                if isinstance(stmt, OutputStmt):
                    val = await self.evaluate_value(stmt.value, env)
                    if stmt.target == 'telegram':
                        await self._builtin_reply(val, mode=stmt.parse_mode, _env=env)
                    else:
                        self._print(str(val))
                elif isinstance(stmt, AssignmentStmt):
                    val = await self.evaluate_value(stmt.value, env)
                    env[stmt.name] = val
                    if "update" not in env: self.global_env[stmt.name] = val
                elif isinstance(stmt, IfChain):
                    for branch in stmt.branches:
                        if branch.condition is None or await self.evaluate_value(branch.condition, env):
                            await self.execute_block(branch.body, env)
                            break
                elif isinstance(stmt, ReturnStmt):
                    val = await self.evaluate_value(stmt.value, env)
                    raise ZyraReturn(val)
                elif isinstance(stmt, (FunctionCallStmt, ExpressionStmt)):
                    expr = stmt.call if isinstance(stmt, FunctionCallStmt) else stmt.expr
                    await self.evaluate_value(expr, env)
                elif isinstance(stmt, ForStmt):
                    iterable = await self.evaluate_value(stmt.iterable, env)
                    if not isinstance(iterable, (list, tuple, str)):
                        raise ZyraRuntimeError(f"'{type(iterable).__name__}' object is not iterable")
                    for item in iterable:
                        env[stmt.item_name] = item
                        await self.execute_block(stmt.body, env)
                elif isinstance(stmt, WhileStmt):
                    while await self.evaluate_value(stmt.condition, env):
                        await self.execute_block(stmt.body, env)
                elif isinstance(stmt, ButtonStmt):
                    keyboard = [[InlineKeyboardButton(stmt.text, callback_data=stmt.callback_name)]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    target = env.get("query", env.get("update"))
                    msg_target = target.message if hasattr(target, "message") else target
                    await msg_target.reply_text("Choose an option:", reply_markup=reply_markup)
                elif isinstance(stmt, (InsertStmt, DbInsertStmt)):
                    if isinstance(stmt, DbInsertStmt):
                        cols = ", ".join(stmt.assignments.keys())
                        vals = [await self.evaluate_value(v, env) for v in stmt.assignments.values()]
                        table = stmt.table
                    else:
                        cols = ", ".join(stmt.assignments.keys())
                        vals = [await self.evaluate_value(v, env) for v in stmt.assignments.values()]
                        table = stmt.table
                    placeholders = ", ".join(["?"] * len(vals))
                    await self._db_execute(f"INSERT INTO {table} ({cols}) VALUES ({placeholders})", tuple(vals))
                elif isinstance(stmt, SendStmt):
                    target = await self.evaluate_value(stmt.target, env)
                    await self._builtin_send(target, stmt.text, _env=env)
                elif isinstance(stmt, (FindStmt, DbFindStmt)):
                    if isinstance(stmt, DbFindStmt):
                        # DbFindStmt: Users.find { id == user.id }
                        # Evaluate condition differently. Currently cond is an Expression.
                        # We just compile it to SQL. This requires an AST to SQL translator for safety.
                        # For now, let's keep it simple: only ComparisonExpr at root
                        if isinstance(stmt.condition, ComparisonExpr):
                            l_val = stmt.condition.left
                            r_val = await self.evaluate_value(stmt.condition.right, env)
                            col = l_val.name if isinstance(l_val, Identifier) else str(l_val)
                            op = "=" if stmt.condition.op == "==" else stmt.condition.op
                            env["result"] = await self._db_fetchone(f"SELECT * FROM {stmt.table} WHERE {col} {op} ?", (r_val,))
                        else:
                            raise ZyraRuntimeError("Invalid find condition. Must be a comparison.")
                    else:
                        l_val = stmt.left
                        r_val = await self.evaluate_value(stmt.right, env)
                        col = l_val.name if isinstance(l_val, Identifier) else str(l_val)
                        op = "=" if stmt.op == "==" else stmt.op
                        env["result"] = await self._db_fetchone(f"SELECT * FROM {stmt.table} WHERE {col} {op} ?", (r_val,))
            except ZyraReturn:
                raise

    async def call_function(self, call: FunctionCall, env: dict) -> Any:
        if os.environ.get("ZYRA_TRACE"):
            self._log(f"[Trace] Calling function at {call.file}:{call.line}")
        fn_def = None
        fn_name = "<anonymous>"
        
        if isinstance(call.target, Identifier):
            fn_name = call.target.name
            if fn_name in self.functions:
                fn_def = self.functions[fn_name]
            elif fn_name in env:
                fn_def = env[fn_name]
            elif fn_name in self.global_env:
                fn_def = self.global_env[fn_name]
        else:
            fn_def = await self.evaluate_value(call.target, env)
            fn_name = str(call.target)

        if fn_def is None:
            raise ZyraRuntimeError(f"Function '{fn_name}' is not defined")
            
        if callable(fn_def):
            resolved_args = []
            for arg in call.args:
                resolved_args.append(await self.evaluate_value(arg, env))
            
            resolved_kwargs = {}
            for k, v in call.kwargs.items():
                resolved_kwargs[k] = await self.evaluate_value(v, env)
            
            if fn_name in ('reply', 'send', 'alert'):
                resolved_kwargs['_env'] = env
                
            res = fn_def(*resolved_args, **resolved_kwargs)
            if asyncio.iscoroutine(res):
                return await res
            return res
            
        if not isinstance(fn_def, FunctionDef):
            raise ZyraRuntimeError(f"'{fn_name}' is not a function")

        if len(call.args) + len(call.kwargs) > len(fn_def.params):
            raise ZyraRuntimeError(f"Function '{fn_name}' expects at most {len(fn_def.params)} arguments, got {len(call.args) + len(call.kwargs)}")
            
        local_env = {}
        # Propagate bot context
        for key in ["_zyra_context", "user", "referrer", "chat", "message", "query", "bot", "chat_id", "now"]:
            if key in env: local_env[key] = env[key]
            
        # Positional args
        for i, arg in enumerate(call.args):
            local_env[fn_def.params[i]] = await self.evaluate_value(arg, env)
            
        # Keyword args
        for k, v in call.kwargs.items():
            if k not in fn_def.params:
                raise ZyraRuntimeError(f"Function '{fn_name}' got unexpected keyword argument '{k}'")
            local_env[k] = await self.evaluate_value(v, env)
            
        try:
            await self.execute_block(fn_def.body, local_env)
        except ZyraReturn as r:
            return r.value
        return None

    def _log(self, *args, **kwargs):
        if os.environ.get("ZYRA_VERBOSE"):
            print(*args, **kwargs)
            sys.stdout.flush()

    def _print(self, *args, **kwargs):
        print(*args, **kwargs)
        sys.stdout.flush()

    async def load_import(self, path: str, alias: str = None):
        if not self.parent:
            self._log(f"[Zyra] Loading module: {path}")
        namespace_name = alias if alias else os.path.splitext(os.path.basename(path.replace('.', os.sep)))[0]
        
        # 1. Check if it's a Zyra file or Python module
        # A path is explicitly Zyra if it ends in .zy or has directory separators
        is_zyra = path.endswith('.zy') or '/' in path or '\\' in path
        
        if not is_zyra:
            # Try to resolve dotted path to a .zy file (e.g. "handlers.start" -> "handlers/start.zy")
            potential_zy_path = path.replace('.', os.sep) + ".zy"
            zy_file = os.path.join(self.base_dir, potential_zy_path)
            if os.path.exists(zy_file):
                path = potential_zy_path
                is_zyra = True

        if not is_zyra:
            # Python Module Import
            if path in self.import_cache:
                module_info = self.import_cache[path]
                self.global_env[namespace_name] = module_info['env']
                return module_info
            
            try:
                import importlib
                py_mod = importlib.import_module(path)
                module_info = {
                    'env': py_mod,
                    'exports': [attr for attr in dir(py_mod) if not attr.startswith('_')]
                }
                self.import_cache[path] = module_info
                self.global_env[namespace_name] = py_mod
                return module_info
            except ImportError:
                raise ZyraRuntimeError(f"Module or file not found: {path}")

        # 2. Zyra File Import
        abs_path = os.path.abspath(os.path.join(self.base_dir, path))
        
        # Python-like caching: check if module is already loaded globally
        if abs_path in self.import_cache:
            module_info = self.import_cache[abs_path]
            self.global_env[namespace_name] = module_info['env']
            return module_info

        if abs_path in self.import_stack: 
            raise ZyraRuntimeError(f"Circular import: {' -> '.join(self.import_stack)} -> {abs_path}")
            
        if not os.path.exists(abs_path): 
            raise ZyraRuntimeError(f"File not found: {path}")
            
        self.import_stack.append(abs_path)
        old_base = self.base_dir
        self.base_dir = os.path.dirname(abs_path)
        try:
            def read_code():
                with open(abs_path, 'r') as f: return f.read()
            code = await asyncio.to_thread(read_code)
            parser = Parser(Lexer(code).tokenize(), file=path)
            sub_interpreter = Interpreter(parent=self)
            await sub_interpreter.setup_handlers(parser.parse())
            
            module_info = {
                'env': sub_interpreter.global_env,
                'exports': sub_interpreter.exported_symbols
            }
            
            # Store in global cache and bind to local namespace
            self.import_cache[abs_path] = module_info
            self.global_env[namespace_name] = sub_interpreter.global_env
            return module_info
        finally:
            self.import_stack.pop()
            self.base_dir = old_base
    async def setup_handlers(self, program: Program):
        # Phase 1 & 2: Loading, Imports, and Definitions
        for stmt in program.statements:
            if os.environ.get("ZYRA_TRACE"):
                self._log(f"[Trace] Processing setup statement: {type(stmt).__name__} at {stmt.file}:{stmt.line}")
            if isinstance(stmt, ImportDef): 
                await self.load_import(stmt.path, stmt.alias)
            elif isinstance(stmt, FromImportDef):
                module_info = await self.load_import(stmt.path)
                for sym in stmt.symbols:
                    if sym not in module_info['exports']:
                        raise ZyraRuntimeError(f"Symbol '{sym}' is not exported from module '{stmt.path}'", stmt)
                    
                    env = module_info['env']
                    val = env[sym] if isinstance(env, dict) else getattr(env, sym)
                    self.global_env[sym] = val
                    if isinstance(val, FunctionDef):
                        self.functions[sym] = val
            elif isinstance(stmt, AssignmentStmt):
                val = await self.evaluate_value(stmt.value, self.global_env)
                self.global_env[stmt.name] = val
                if stmt.is_export:
                    self.exported_symbols[stmt.name] = val
            elif isinstance(stmt, FunctionDef): 
                self.functions[stmt.name] = stmt
                self.global_env[stmt.name] = stmt # For namespacing
                if stmt.is_export:
                    self.exported_symbols[stmt.name] = stmt
        
        # Phase 3: Registration and Execution
        for stmt in program.statements:
            if isinstance(stmt, TokenDef):
                token = await self.evaluate_value(stmt.source, self.global_env)
                if token:
                    self.global_env['token'] = token
                    self.app = Application.builder().token(str(token)).build()
                    if self.parent: self.parent.app = self.app
            elif isinstance(stmt, BotDef):
                bot_name = await self.evaluate_value(stmt.source, self.global_env)
                self.global_env['bot_name'] = bot_name
            elif isinstance(stmt, AIDef):
                self.ai_config["provider"] = stmt.provider
                self.ai_config["model"] = stmt.model
            elif isinstance(stmt, TableDef):
                fields_sql = [f"{f.name} {'INTEGER' if f.type_ == 'integer' else 'TEXT'}{' PRIMARY KEY' if f.is_primary else ''}" for f in stmt.fields]
                await self._db_execute(f"CREATE TABLE IF NOT EXISTS {stmt.name} ({', '.join(fields_sql)})")
            elif isinstance(stmt, (CommandDef, MessageContainsDef, CallbackDef, EveryDef, StateDef, EventStmt)):
                self.pending_handlers.append(stmt)
            elif isinstance(stmt, (IfChain, FunctionCallStmt, OutputStmt, ExpressionStmt, ForStmt, WhileStmt, InsertStmt, DbInsertStmt, FindStmt, DbFindStmt)):
                await self.execute_block([stmt], self.global_env)

        # Finalize Application setup if token exists and not already created
        if 'token' in self.global_env and not self.app:
            token = self.global_env['token']
            self.app = Application.builder().token(str(token)).build()
            if self.parent: self.parent.app = self.app

    def register_handlers(self):
        if not self.app: return
        for stmt in self.pending_handlers:
            if isinstance(stmt, CommandDef):
                cmd_id = stmt.command.lstrip('/')
                self._log(f"[Zyra] Registered command: {stmt.command}")
                self.app.add_handler(CommandHandler(cmd_id, self.make_handler(stmt.body, command_name=stmt.command)))
            elif isinstance(stmt, MessageContainsDef):
                self._log(f"[Zyra] Registered message handler: {stmt.text}")
                self.app.add_handler(MessageHandler(filters.Regex(f".*{stmt.text}.*"), self.make_handler(stmt.body)))
            elif isinstance(stmt, CallbackDef):
                self._log(f"[Zyra] Registered callback: {stmt.name}")
                self.app.add_handler(CallbackQueryHandler(self.make_handler(stmt.body, is_callback=True), pattern=f"^{stmt.name}$"))
            elif isinstance(stmt, EventStmt):
                self._log(f"[Zyra] Registered event: {stmt.event_type} {stmt.event_value or ''}")
                if stmt.event_type == 'command':
                    cmd_id = stmt.event_value.lstrip('/')
                    self.app.add_handler(CommandHandler(cmd_id, self.make_handler(stmt.body, command_name=stmt.event_value)))
                elif stmt.event_type == 'message':
                    if stmt.event_value:
                        self.app.add_handler(MessageHandler(filters.Regex(f".*{stmt.event_value}.*"), self.make_handler(stmt.body)))
                    else:
                        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.make_handler(stmt.body)))
                elif stmt.event_type == 'callback_query' or stmt.event_type == 'callback':
                    self.app.add_handler(CallbackQueryHandler(self.make_handler(stmt.body, is_callback=True), pattern=f"^{stmt.event_value}$" if stmt.event_value else None))
                elif stmt.event_type == 'join_request':
                    from telegram.ext import ChatJoinRequestHandler
                    self.app.add_handler(ChatJoinRequestHandler(self.make_handler(stmt.body)))
                elif stmt.event_type == 'new_chat_members':
                    from telegram.ext import MessageHandler, filters
                    self.app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, self.make_handler(stmt.body)))
            elif isinstance(stmt, EveryDef):
                self._log(f"[Zyra] Registered schedule: {stmt.interval}")
                unit = stmt.interval[-1]
                val = int(stmt.interval[:-1])
                kwargs = {"minutes": val} if unit == 'm' else {"hours": val} if unit == 'h' else {"seconds": val}
                self.scheduler.add_job(self.make_job(stmt.body), 'interval', **kwargs)
            elif isinstance(stmt, StateDef):
                self._log(f"[Zyra] Registered state: {stmt.name}")
                self.app.add_handler(self.make_conversation_handler(stmt))

    async def _handle_referral(self, update: Update) -> Any:
        if not update.effective_user or not update.message or not update.message.text:
            return None
            
        user_id = update.effective_user.id
        text = update.message.text

        if text.startswith('/start '):
            parts = text.split(' ', 1)
            if len(parts) < 2: 
                self._log("[REFERRAL] No referrer")
                return None
            payload = parts[1].strip()
            self._log(f"[REFERRAL] Payload: {payload}")
            
            # Validation: Must be exactly 10 characters and an integer
            if len(payload) != 10:
                self._log("[REFERRAL] No referrer (invalid length)")
                return None
            
            # User cannot refer themselves
            if payload == str(user_id):
                self._log("[REFERRAL] No referrer (self-referral)")
                return None
            
            try:
                ref_id = int(payload)
                self._log(f"[REFERRAL] Referrer detected: {ref_id}")
                return ref_id
            except ValueError:
                self._log("[REFERRAL] No referrer (not an integer)")
                return None
        
        self._log("[REFERRAL] No referrer")
        return None

    def make_handler(self, body: List[Statement], command_name: str = None, is_callback=False):
        async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            try:
                if command_name:
                    self._log(f"[Zyra] Executing command: {command_name}")
                
                referrer = await self._handle_referral(update)
                zyra_ctx = ZyraContext(update, context, referrer=referrer)
                # Build standard Zyra execution environment
                env = {
                    "update": update,
                    "context": context,
                    "_zyra_context": zyra_ctx,
                    "user": zyra_ctx.user,
                    "referrer": referrer,
                    "chat": zyra_ctx.chat,
                    "message": zyra_ctx.message,
                    "query": zyra_ctx.query,
                    "bot": zyra_ctx.bot,
                    "chat_id": zyra_ctx.chat_id,
                    "now": zyra_ctx.now,
                    "args": context.args if context else []
                }
                
                if is_callback:
                    if update.callback_query:
                        env["query"] = update.callback_query
                        env["_callback_answered"] = False
                
                await self.execute_block(body, env)
                
                # Auto-answer callback if not already answered by alert()
                if is_callback and update.callback_query and not env.get("_callback_answered"):
                    await update.callback_query.answer()
            except ZyraReturn:
                pass
            except ZyraRuntimeError as e:
                self._print(str(e))
            except Exception as e:
                if self.current_node:
                    self._print(f"Zyra Runtime Error:\nFile: {self.current_node.file}:{self.current_node.line}\nError: {str(e)}")
                else:
                    self._print(f"Zyra Runtime Error: {str(e)}")
        return handler

    def make_job(self, body: List[Statement]):
        async def job():
            try:
                zyra_ctx = ZyraContext(None, None)
                setattr(zyra_ctx, '_context', type('obj', (object,), {'bot': self.app.bot}))
                env = {"_zyra_context": zyra_ctx, "bot": self.app.bot}
                await self.execute_block(body, env)
            except ZyraReturn:
                pass
            except Exception as e:
                self._print(f"Zyra Job Error: {str(e)}")
        return job

    def make_conversation_handler(self, state_def: StateDef):
        name = state_def.name.lower()
        steps = [stmt for stmt in state_def.body if isinstance(stmt, (AskStmt, SaveStmt, ReplyStmt, IfChain, FunctionCallStmt, OutputStmt))]
        async def entry_point(update: Update, context: ContextTypes.DEFAULT_TYPE):
            context.user_data[f"{name}_step"] = 0
            return await execute_step(update, context)
        async def state_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            step_idx = context.user_data.get(f"{name}_step", 0)
            stmt = steps[step_idx]
            if isinstance(stmt, AskStmt):
                if step_idx + 1 < len(steps) and isinstance(steps[step_idx+1], SaveStmt):
                    save_stmt = steps[step_idx+1]
                    context.user_data[save_stmt.variable] = update.message.text
                    context.user_data[f"{name}_step"] = step_idx + 2
                    return await execute_step(update, context)
            return ConversationHandler.END
        async def execute_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
            step_idx = context.user_data.get(f"{name}_step", 0)
            while step_idx < len(steps):
                stmt = steps[step_idx]
                if isinstance(stmt, AskStmt):
                    await update.message.reply_text(stmt.text)
                    context.user_data[f"{name}_step"] = step_idx
                    return 1
                elif isinstance(stmt, SaveStmt):
                    step_idx += 1
                    context.user_data[f"{name}_step"] = step_idx
                elif isinstance(stmt, (ReplyStmt, OutputStmt)):
                    env = {"update": update, "context": context}
                    for k,v in context.user_data.items(): env[k] = v
                    val = await self.evaluate_value(stmt.value if isinstance(stmt, OutputStmt) else stmt.text, env)
                    await update.message.reply_text(str(val))
                    step_idx += 1
                    context.user_data[f"{name}_step"] = step_idx
                elif isinstance(stmt, IfChain):
                    step_idx += 1
                    context.user_data[f"{name}_step"] = step_idx
                elif isinstance(stmt, FunctionCallStmt):
                    env = {"update": update, "context": context}
                    for k,v in context.user_data.items(): env[k] = v
                    await self.call_function(stmt.call, env)
                    step_idx += 1
                    context.user_data[f"{name}_step"] = step_idx
            return ConversationHandler.END
        return ConversationHandler(
            entry_points=[CommandHandler(name, entry_point)],
            states={1: [MessageHandler(filters.TEXT & ~filters.COMMAND, state_handler)]},
            fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)]
        )

    async def run(self, program: Program):
        logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.INFO)
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("telegram").setLevel(logging.INFO)
        
        try:
            self._log("[Zyra] Starting engine...")
            self.pending_handlers = []
            await self.setup_handlers(program)
            
            if not self.app:
                if 'token' not in self.global_env:
                    raise ZyraRuntimeError("Bot token not defined in script")
                token = self.global_env['token']
                self.app = Application.builder().token(str(token)).build()

            self.register_handlers()
            if self.scheduler.get_jobs(): self.scheduler.start()
            
            # THE SNIFFER: Prints EVERY interaction
            async def sniffer(update: Update, context: ContextTypes.DEFAULT_TYPE):
                self._log(f"[Zyra] >>> DATA ARRIVED! ID: {update.update_id}")
                if update.message:
                    self._log(f"[Zyra] >>> MESSAGE TEXT: '{update.message.text}'")
            self.app.add_handler(MessageHandler(filters.ALL, sniffer), group=-100)

            self._log("[Zyra] Resetting Telegram connection...")
            await self.app.initialize()
            await self.app.bot.delete_webhook(drop_pending_updates=True)
            
            self._log("[Zyra] Starting update poller...")
            await self.app.updater.start_polling(drop_pending_updates=True)
            await self.app.start()
            
            bot_info = await self.app.bot.get_me()
            self._log(f"[Zyra] Bot is live: @{bot_info.username}")
            self._log("[Zyra] System ready. Waiting for messages...")
            
            while True:
                await asyncio.sleep(3600)
        except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
            if self.app:
                await self.app.updater.stop()
                await self.app.stop()
                await self.app.shutdown()
        except ZyraRuntimeError as e:
            self._print(str(e))
            sys.exit(1)
        except Exception as e:
            if self.current_node:
                self._print(f"Zyra Runtime Error:\nFile: {self.current_node.file}:{self.current_node.line}\nError: {str(e)}")
            else:
                self._print(f"Zyra Runtime Error: {str(e)}")
            if os.environ.get("ZYRA_DEBUG"):
                import traceback
                traceback.print_exc()
            sys.exit(1)
