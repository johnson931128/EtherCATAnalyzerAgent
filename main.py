from graph import graph


if __name__ == "__main__":
    print("EtherCAT Analyzer Agent")
    print("輸入 exit 離開")

    while True:
        task = input("\n> ").strip()

        if task.lower() in {"exit", "quit", "q"}:
            break

        if not task:
            continue

        result = graph.invoke({
            "task": task
        })

        print(f"\nSelected docs:\n{result['selected_docs']}")
        print(f"\nSelected source: {result['selected_source']}")
        print(f"Capture mode: {result['capture_mode']}")
        print()
        print(result["result"])
