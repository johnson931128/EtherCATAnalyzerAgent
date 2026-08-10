from langchain_openai import ChatOpenAI


llm = ChatOpenAI(
    model="Qwen/Qwen3.5-122B-A10B",
    base_url="http://127.0.0.1:5000/v1",
    api_key="local-proxy",
    temperature=0,
    timeout=120,
    max_retries=0,
)


response = llm.invoke("只回覆這句話：EtherCAT Agent 連線成功")

print(response.content)