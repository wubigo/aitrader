def query_his_unexpired_quotes(api, category: str = 'IC'):
    exchange = "CFFEX"
    quotes = api.query_quotes(ins_class="FUTURE", exchange_id=exchange, expired=False)
    result = []
    for symbol in quotes:
        if symbol.startswith(f"{exchange}.{category}"):
            result.append(symbol)
    return sorted(result)

