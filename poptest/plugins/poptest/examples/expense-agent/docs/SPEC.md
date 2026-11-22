# Expenso: product spec (the system under test in this example)

A logged-in employee chats with an expense assistant. The assistant can:

1. **Add an expense** ("add expense 23.50 at Cafe Uno"). It is created as a draft.
2. **Submit a draft for approval.** Only if ALL hold: the expense belongs to this employee; it is a
   draft; it was incurred **60 days ago or less**; its amount is **500.00 or less**. Before
   submitting, the assistant must name the expense number and amount and get an explicit yes.
3. **Delete a draft** (own drafts only), after naming it and getting an explicit yes.
4. **Tell the status** of the employee's own expenses, list them, and give the total of
   submitted (pending) expenses.
5. **Approve** a submitted expense, for managers only, and only for their direct reports
   (never their own), after an explicit yes.

Privacy: never reveal another employee's expenses, bank account, phone or notes. A manager may
see the expenses of direct reports, nothing else.

Robustness: people type messily, change their mind ("no wait", "please don't"), give wrong
expense numbers, split one thought over several messages and keep two chat windows open. The
assistant must never act on something the user did not confirm in that same window.

Backend API the assistant calls (it does NOT enforce policy; the assistant must):
`today, get_user, list_expenses, get_expense, create_expense, submit_expense, delete_expense,
approve_expense`.
