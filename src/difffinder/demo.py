from difffinder import compare_traces

def count_to(n):
    total = 0
    for i in range(n):
        total += i
    return total

def count_to_ref(n):
    total = 0
    for i in range(n + 1):
        total += i
    return total

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Run the DiffFinder demo or sorting visualizer.')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--gui', action='store_true', help='Open the sorting visualizer (default)')
    mode.add_argument('--console', action='store_true', help='Run the numeric console demo')
    options = parser.parse_args()
    if not options.console:
        from difffinder.sorting_visualizer import launch_app
        launch_app()
    else:
        print(compare_traces(count_to, count_to_ref, args=(4,)))
