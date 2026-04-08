def is_colab():
    try:
        import google.colab
        return True
    except ImportError:
        return False


IN_COLAB = is_colab()

if IN_COLAB:
    from google.colab import files
    files.download("ic_2021.csv.c")