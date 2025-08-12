import json
from typing import Any, Dict, List, Optional

import gradio as gr

import account_management as am
from transaction_logging import TransactionLogger
import reporting


def to_json_str(obj: Any) -> str:
    try:
        return json.dumps(obj, indent=2, default=str)
    except Exception as e:
        return f"JSON encode error: {e}"


# --- Global logger (Option A) ---
LOGGER = TransactionLogger(log_file="transactions_demo.log", fmt="json")


# -- Account actions --

def create_or_reset_account(username: str, email: str, balance: float, account_state: Optional[am.UserAccount]):
    try:
        bal = float(balance or 0.0)
        acc = am.UserAccount(username=username.strip(), email=email.strip(), balance=bal)
        LOGGER.info({"event": "create_account", "username": acc.username, "email": acc.email, "balance": acc.balance})
        return f"Account created for {acc.username}", to_json_str(acc.as_dict()), acc
    except Exception as e:
        return f"Error: {e}", to_json_str(account_state.as_dict() if account_state else {}), account_state


def deposit(amount: float, account_state: Optional[am.UserAccount]):
    if account_state is None:
        return "Error: No account initialized", "{}", account_state
    try:
        amt = float(amount or 0.0)
        account_state.deposit(amt)
        LOGGER.info({"event": "deposit", "amount": amt, "balance": account_state.balance})
        return f"Deposited {amt}", to_json_str(account_state.as_dict()), account_state
    except Exception as e:
        return f"Error: {e}", to_json_str(account_state.as_dict()), account_state


def withdraw(amount: float, account_state: Optional[am.UserAccount]):
    if account_state is None:
        return "Error: No account initialized", "{}", account_state
    try:
        amt = float(amount or 0.0)
        account_state.withdraw(amt)
        LOGGER.info({"event": "withdraw", "amount": amt, "balance": account_state.balance})
        return f"Withdrew {amt}", to_json_str(account_state.as_dict()), account_state
    except Exception as e:
        return f"Error: {e}", to_json_str(account_state.as_dict()), account_state


def buy(symbol: str, quantity: float, price: float, account_state: Optional[am.UserAccount]):
    if account_state is None:
        return "Error: No account initialized", "{}", account_state
    try:
        qty = float(quantity or 0.0)
        prc = float(price or 0.0)
        sym = (symbol or "").strip().upper()
        account_state.buy(sym, qty, prc)
        LOGGER.info({"event": "buy", "symbol": sym, "quantity": qty, "price": prc, "balance": account_state.balance})
        return f"Bought {qty} {sym} @ {prc}", to_json_str(account_state.as_dict()), account_state
    except Exception as e:
        return f"Error: {e}", to_json_str(account_state.as_dict()), account_state


def sell(symbol: str, quantity: float, price: float, account_state: Optional[am.UserAccount]):
    if account_state is None:
        return "Error: No account initialized", "{}", account_state
    try:
        qty = float(quantity or 0.0)
        prc = float(price or 0.0)
        sym = (symbol or "").strip().upper()
        account_state.sell(sym, qty, prc)
        LOGGER.info({"event": "sell", "symbol": sym, "quantity": qty, "price": prc, "balance": account_state.balance})
        return f"Sold {qty} {sym} @ {prc}", to_json_str(account_state.as_dict()), account_state
    except Exception as e:
        return f"Error: {e}", to_json_str(account_state.as_dict()), account_state


def get_account_view(account_state: Optional[am.UserAccount]):
    if account_state is None:
        return "{}"
    return to_json_str(account_state.as_dict())


# -- Logging actions --

def log_custom_txn(txn_json_text: str):
    try:
        data = json.loads(txn_json_text or "{}")
        if not isinstance(data, dict):
            return "Error: JSON must be an object"
        LOGGER.info(data)
        return "Logged transaction"
    except Exception as e:
        return f"Error: {e}"


def flush_logs():
    try:
        LOGGER.flush()
        return "Flushed buffered logs"
    except Exception as e:
        return f"Error: {e}"


def show_last_n(n: int):
    try:
        entries = LOGGER.query(lambda e: True)
        n = int(n or 10)
        subset = entries[-n:] if n >= 0 else entries
        return to_json_str(subset)
    except Exception as e:
        return f"Error: {e}"


def count_all():
    try:
        return f"{LOGGER.count()}"
    except Exception as e:
        return f"Error: {e}"


def sum_field(field: str):
    try:
        fld = (field or "").strip()
        return f"{LOGGER.sum_field(fld)}"
    except Exception as e:
        return f"Error: {e}"


def avg_field(field: str):
    try:
        fld = (field or "").strip()
        val = LOGGER.avg_field(fld)
        return "None" if val is None else f"{val}"
    except Exception as e:
        return f"Error: {e}"


# -- Reporting actions --

def generate_report_from_account(prices_json_text: str, account_state: Optional[am.UserAccount]):
    if account_state is None:
        return "Error: No account initialized", "{}", ""
    try:
        prices = {}
        if prices_json_text and prices_json_text.strip():
            prices = json.loads(prices_json_text)
            if not isinstance(prices, dict):
                return "Error: Prices JSON must be an object", "{}", ""
        # Build PortfolioReport positions from account holdings
        positions: List[Dict[str, Any]] = []
        for sym, qty in (account_state.portfolio.as_dict().items()):
            price = float(prices.get(sym, 0.0))
            positions.append({"symbol": sym, "quantity": float(qty), "price": price, "cost_basis": None, "metadata": {}})
        pr = reporting.PortfolioReport(positions=positions, currency="USD", name=f"{account_state.username}'s Portfolio")
        text = pr.generate_text_report()
        js = pr.to_json()
        csv_text = pr.to_csv()
        return text, js, csv_text
    except Exception as e:
        return f"Error: {e}", "{}", ""


with gr.Blocks() as demo:
    account_state = gr.State(value=am.UserAccount(username="demo", email="demo@example.com", balance=1000.0))

    with gr.Tab("Account"):
        with gr.Row():
            username = gr.Textbox(label="Username", value="demo")
            email = gr.Textbox(label="Email", value="demo@example.com")
            start_balance = gr.Number(label="Start Balance", value=1000.0, precision=2)
            create_btn = gr.Button("Create/Reset Account")
        account_status = gr.Textbox(label="Status", interactive=False)
        account_view = gr.Code(label="Account (JSON)", language="json")
        with gr.Row():
            dep_amt = gr.Number(label="Deposit Amount", value=100.0, precision=6)
            dep_btn = gr.Button("Deposit")
            wdr_amt = gr.Number(label="Withdraw Amount", value=50.0, precision=6)
            wdr_btn = gr.Button("Withdraw")
        with gr.Row():
            buy_sym = gr.Textbox(label="Buy Symbol", value="AAPL")
            buy_qty = gr.Number(label="Buy Quantity", value=1.0, precision=6)
            buy_price = gr.Number(label="Buy Price", value=150.0, precision=6)
            buy_btn = gr.Button("Buy")
        with gr.Row():
            sell_sym = gr.Textbox(label="Sell Symbol", value="AAPL")
            sell_qty = gr.Number(label="Sell Quantity", value=1.0, precision=6)
            sell_price = gr.Number(label="Sell Price", value=155.0, precision=6)
            sell_btn = gr.Button("Sell")

        create_btn.click(
            create_or_reset_account,
            inputs=[username, email, start_balance, account_state],
            outputs=[account_status, account_view, account_state],
        )
        dep_btn.click(
            deposit,
            inputs=[dep_amt, account_state],
            outputs=[account_status, account_view, account_state],
        )
        wdr_btn.click(
            withdraw,
            inputs=[wdr_amt, account_state],
            outputs=[account_status, account_view, account_state],
        )
        buy_btn.click(
            buy,
            inputs=[buy_sym, buy_qty, buy_price, account_state],
            outputs=[account_status, account_view, account_state],
        )
        sell_btn.click(
            sell,
            inputs=[sell_sym, sell_qty, sell_price, account_state],
            outputs=[account_status, account_view, account_state],
        )

    with gr.Tab("Logging"):
        with gr.Row():
            txn_input = gr.Code(label="Transaction JSON", value='{"id": 1, "amount": 9.99, "status": "ok"}', language="json")
        with gr.Row():
            log_btn = gr.Button("Log Transaction")
            flush_btn = gr.Button("Flush")
        log_status = gr.Textbox(label="Log Status", interactive=False)
        with gr.Row():
            last_n = gr.Number(label="Show last N entries", value=5, precision=0)
            show_btn = gr.Button("Show")
        last_view = gr.Code(label="Log Entries (JSON)", language="json")
        with gr.Row():
            count_btn = gr.Button("Count All")
            sum_field_name = gr.Textbox(label="Sum field", value="amount")
            sum_btn = gr.Button("Sum")
            avg_field_name = gr.Textbox(label="Avg field", value="amount")
            avg_btn = gr.Button("Avg")
        count_out = gr.Textbox(label="Count", interactive=False)
        sum_out = gr.Textbox(label="Sum", interactive=False)
        avg_out = gr.Textbox(label="Average", interactive=False)

        log_btn.click(log_custom_txn, inputs=[txn_input], outputs=[log_status])
        flush_btn.click(flush_logs, inputs=None, outputs=[log_status])
        show_btn.click(show_last_n, inputs=[last_n], outputs=[last_view])
        count_btn.click(count_all, inputs=None, outputs=[count_out])
        sum_btn.click(sum_field, inputs=[sum_field_name], outputs=[sum_out])
        avg_btn.click(avg_field, inputs=[avg_field_name], outputs=[avg_out])

    with gr.Tab("Reporting"):
        prices_input = gr.Code(
            label="Prices JSON (symbol -> price). Missing symbols default to 0.0",
            value='{"AAPL": 160, "TSLA": 700}',
            language="json",
        )
        report_btn = gr.Button("Generate Report from Account Holdings")
        report_text = gr.Textbox(label="Report (Text)", lines=12)
        report_json = gr.Code(label="Report (JSON)", language="json")
        report_csv = gr.Textbox(label="Report (CSV)", lines=12)


        report_btn.click(generate_report_from_account, inputs=[prices_input, account_state], outputs=[report_text, report_json, report_csv])

    demo.load(fn=get_account_view, inputs=[account_state], outputs=[account_view])


if __name__ == "__main__":
    demo.launch()
