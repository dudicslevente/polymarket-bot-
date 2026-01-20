trades = []
main = 'trades.csv'
with open(main, 'r', encoding='utf-8') as forras:
    coloumns = forras.readline()
    for sor in forras:
        egysor = sor.strip().split(',')
        trades.append(float(egysor[15]))
pnl = sum(trades)
print(round(pnl, 2))