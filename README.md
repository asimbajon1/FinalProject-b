# Instructions and Guidelines

## Notes
```
No need to test email. Email accounts not active.
The test_concurrent_updates_to_version_are_not_allowed in test_uow is commented out. 
    Similar test is already covered in test_batches.
```

## Creating a local virtual environment
```
py -3 -m venv venv
```

## Pip installs
```
pip install -r requirements.txt
pip install -e src/
```

## Running the tests
```
pytest tests/unit
pytest tests/integration
pytest tests/e2e
```

## Final project essay
Please find the Final Project - Allan Simbajon.pdf file