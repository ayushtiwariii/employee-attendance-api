# Engineering Decisions

1. **Indexes.** A unique index on `employees.emp_code` protects employee identity. A compound unique index on `(emp_code, date)` makes one attendance row per employee/day a database invariant. Department/join-date, attendance date/employee, employee/date/status, and date/late indexes support the principal filters, sorts, lookups, and reporting queries. Indexes improve reads but consume disk and make writes somewhat more expensive.

2. **Simultaneous punch-ins.** Both requests may reach MongoDB, but the unique compound attendance index allows only one insert for that employee and date. The winner receives 201; a duplicate-key loser receives 409. A preliminary read is not used as the concurrency guarantee.

3. **Leaderboard cutoff ties.** MongoDB `$rank` assigns equal totals the same rank and skips the next rank (1, 2, 2, 4). Filtering is applied to `rank <= limit`, so ties at the cutoff are all returned. Final rows are ordered by total minutes descending and employee code ascending.

4. **Department headcount.** The summary starts from employees who joined on or before the month end and looks up their attendance. Employees without logs remain in the aggregation and count toward headcount; employees who join later are excluded. Work-hour averages are calculated over eligible attendance records, not averages of employee averages.

5. **100x data.** Keep the aggregation server-side, verify real explain plans and index selectivity, benchmark with production-like distributions, and consider time-bounded archival/partitioning or a reporting read model if needed. Avoid speculative indexes without measurements; monitor index size, write cost, and examined-document counts.
