idok = []
backtest = 'backtest_results.csv'
main = 'trades.csv'
with open(main, 'r', encoding='utf-8') as forras:
    coloumns = forras.readline()
    for sor in forras:
        egysor = sor.strip().split(',')
        idok.append(egysor[0].split('T')[0])

set_idok = set(idok)
szamlalo = {}
for ido in set_idok:
    szamlalo[ido] = 0

for ido in idok:
    szamlalo[ido] += 1

# print(szamlalo)
osszes_nap = len(set_idok)
osszes_trade = 0
for ido in set_idok:
    osszes_trade += szamlalo[ido]
# print(osszes_nap, osszes_trade)
print(f'Average trade per day:', round(osszes_trade/osszes_nap, 2))