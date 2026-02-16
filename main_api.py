import uvicorn

if __name__ == "__main__":
    print("=" * 60)
    print("  task_sync PWA サーバー")
    print("=" * 60)
    print()
    print("  PC:     http://localhost:8000")
    print("  スマホ: http://<PCのIP>:8000")
    print()
    print("  停止: Ctrl+C")
    print("=" * 60)
    uvicorn.run("backend.api:app", host="0.0.0.0", port=8000)
