import pandas as pd
# 示例
data = {'姓名': ['A', 'B', 'C', 'D', 'E', 'F'],
        '分数': [80, 95, 70, 90, 85, 100]}
df = pd.DataFrame(data)

top_5_students = df.nlargest(5, '分数')
print(top_5_students)

print(df['姓名'])
