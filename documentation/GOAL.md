We want to answer one question: Can an AI agent make an application faster by tailoring one of its libraries specifically for that application?

A general-purpose library handles many situations. A particular application may only need some of them. If we can establish what the application actually requires, we may be able to simplify the library’s work without changing the application’s behavior.

The intended result is a replacement library that:

- Works through the application’s existing interface.
- Preserves all supported behavior, including errors and uncommon inputs.
- Reduces library work time by the configured target, while reporting complete application time separately.
- Comes with tests and instructions that let someone independently verify the improvement.
