from datetime import datetime, timedelta
import utils.ak as ak_util
import akshare as ak
import pandas as pd

end_date = datetime.now()
start_date = end_date - timedelta(days=60)
start_str = start_date.strftime("%Y%m%d")
end_str = end_date.strftime("%Y%m%d")

# pd = ak_util.index_publish_daily_sw(symbol="801120", start_date=start_str, end_date=end_str)
# print(pd)

# ak.index_analysis_daily_sw()
# pd = ak_util.index_analysis_daily_sw(index_code="all")
# pd = pd[["指数代码", "指数名称"]]
# pd.to_csv(f"../data/申万一级行业列表.csv", index=True, encoding="utf-8-sig")

# 读取申万一级行业列表
industry_df = pd.read_csv("../data/申万一级行业列表.csv", encoding="utf-8-sig")
print(f"共读取 {len(industry_df)} 个行业")

# 循环查询所有行业的成分股
all_results = []

for idx, row in industry_df.iterrows():
    index_code = row['指数代码']
    index_name = row['指数名称']
    
    print(f"\n[{idx+1}/{len(industry_df)}] 查询 {index_name} ({index_code}) ...")
    
    try:
        # 查询成分股
        component_df = ak.index_component_sw(symbol=index_code)
        
        if not component_df.empty:
            # 添加指数名称列
            component_df['指数名称'] = index_name
            
            # 添加计入日期（当前日期）
            component_df['计入日期'] = datetime.now().strftime('%Y-%m-%d')
            
            # 重命名列以匹配目标格式
            component_df = component_df.rename(columns={
                '股票代码': '证券代码',
                '股票名称': '证券名称',
                '最新权重': '最新权重'
            })
            
            # 选择需要的列
            component_df = component_df[['证券代码', '证券名称', '最新权重', '计入日期', '指数名称']]
            
            all_results.append(component_df)
            print(f"  ✓ 获取到 {len(component_df)} 只成分股")
        else:
            print(f"  ✗ 无数据")
    except Exception as e:
        print(f"  ✗ 查询失败：{e}")
        continue

# 合并所有结果
if all_results:
    result_df = pd.concat(all_results, ignore_index=True)
    
    # 保存到 CSV
    output_file = f"../data/申万行业成分股_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    result_df.to_csv(output_file, index=False, encoding="utf-8-sig")
    
    print(f"\n保存完成！共 {len(result_df)} 条记录")
    print(f"文件路径：{output_file}")
else:
    print("\n未获取到任何数据")

