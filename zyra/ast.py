from dataclasses import dataclass
from typing import List, Optional, Any, Dict

class ASTNode:
    line: int = 0
    column: int = 0
    file: str = "unknown"

@dataclass
class NamedArg(ASTNode):
    name: str
    value: Any

@dataclass
class Program(ASTNode):
    statements: List['Statement']

@dataclass
class Statement(ASTNode):
    pass

@dataclass
class Identifier(ASTNode):
    name: str

@dataclass
class StringLiteral(ASTNode):
    value: str

@dataclass
class StringTemplate(ASTNode):
    parts: List[Any] # Mixed StringLiteral and Expression nodes

@dataclass
class NullLiteral(ASTNode):
    pass

@dataclass
class NumberLiteral(ASTNode):
    value: str

@dataclass
class ListLiteral(ASTNode):
    elements: List[Any]

@dataclass
class MemberAccess(ASTNode):
    target: Any
    member: str

@dataclass
class LogicExpr(ASTNode):
    left: Any
    op: str
    right: Any

@dataclass
class UnaryExpr(ASTNode):
    op: str
    right: Any

@dataclass
class ComparisonExpr(ASTNode):
    left: Any
    op: str
    right: Any

@dataclass
class BinaryExpr(ASTNode):
    left: Any
    op: str
    right: Any

@dataclass
class IfBranch:
    condition: Optional[Any] # None for 'else'
    body: List[Statement]

@dataclass
class IfChain(Statement):
    branches: List[IfBranch]

@dataclass
class ForStmt(Statement):
    item_name: str
    iterable: Any
    body: List[Statement]

@dataclass
class WhileStmt(Statement):
    condition: Any
    body: List[Statement]

@dataclass
class ExpressionStmt(Statement):
    expr: Any

@dataclass
class DbInsertStmt(Statement):
    table: str
    assignments: dict

@dataclass
class DbFindStmt(Statement):
    table: str
    condition: Any

@dataclass
class EventStmt(Statement):
    event_type: str
    event_value: Optional[str]
    body: List[Statement]

@dataclass
class FunctionDef(Statement):
    name: str
    params: List[str]
    body: List[Statement]
    is_export: bool = False

@dataclass
class BotDef(Statement):
    source: Any

@dataclass
class ReturnStmt(Statement):
    value: Any

@dataclass
class FunctionCall(ASTNode):
    target: Any
    args: List[Any]
    kwargs: Dict[str, Any]

@dataclass
class FunctionCallStmt(Statement):
    call: FunctionCall

@dataclass
class OutputStmt(Statement):
    value: Any
    target: str # 'telegram' or 'console'
    parse_mode: Optional[str] = None

@dataclass
class TokenDef(Statement):
    source: Any 

@dataclass
class CommandDef(Statement):
    command: str
    body: List[Statement]

@dataclass
class MessageContainsDef(Statement):
    text: str
    body: List[Statement]

@dataclass
class CallbackDef(Statement):
    name: str
    body: List[Statement]

@dataclass
class AssignmentStmt(Statement):
    name: str
    value: Any
    is_export: bool = False

@dataclass
class ReplyStmt(Statement):
    # Legacy, will be replaced by OutputStmt in parser
    text: Any

@dataclass
class ButtonStmt(Statement):
    text: str
    callback_name: str

@dataclass
class AdminDef(Statement):
    source: str
    is_env: bool

@dataclass
class ImportDef(Statement):
    path: str
    alias: Optional[str] = None

@dataclass
class FromImportDef(Statement):
    path: str
    symbols: List[str]

@dataclass
class PluginDef(Statement):
    name: str

@dataclass
class AskStmt(Statement):
    text: str

@dataclass
class SaveStmt(Statement):
    variable: str

@dataclass
class StateDef(Statement):
    name: str
    body: List[Statement]

@dataclass
class TableField:
    name: str
    type_: str
    is_primary: bool

@dataclass
class TableDef(Statement):
    name: str
    fields: List[TableField]

@dataclass
class InsertStmt(Statement):
    table: str
    assignments: dict

@dataclass
class FindStmt(Statement):
    table: str
    left: Any
    op: str
    right: Any

@dataclass
class EveryDef(Statement):
    interval: str
    body: List[Statement]

@dataclass
class SendStmt(Statement):
    target: Any
    text: str

@dataclass
class AIDef(Statement):
    provider: str
    model: str

@dataclass
class AIReplyStmt(Statement):
    text: Any
