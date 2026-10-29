#include "jarvis_speech_onnx_fixture.h"

#include <stdio.h>
#include <string.h>

#define MODEL_CAPACITY (1024u * 1024u)
#define REPEAT_LIFECYCLES 100u

static int failures = 0;
static int checks = 0;
static unsigned char model_data[MODEL_CAPACITY];
static size_t model_bytes = 0u;

#define CHECK(condition)                                                        \
    do {                                                                        \
        ++checks;                                                               \
        if (!(condition)) {                                                     \
            ++failures;                                                         \
            fprintf(stderr, "check failed at %s:%d: %s\n", __FILE__, __LINE__, \
                    #condition);                                                \
        }                                                                       \
    } while (0)

static int load_model(const char *path) {
    FILE *file = NULL;
    long length;
    size_t bytes_read;
    if (path == NULL || fopen_s(&file, path, "rb") != 0 || file == NULL) {
        return -1;
    }
    if (fseek(file, 0, SEEK_END) != 0) {
        (void)fclose(file);
        return -1;
    }
    length = ftell(file);
    if (length <= 0 || (unsigned long)length > MODEL_CAPACITY ||
        fseek(file, 0, SEEK_SET) != 0) {
        (void)fclose(file);
        return -1;
    }
    bytes_read = fread(model_data, 1u, (size_t)length, file);
    (void)fclose(file);
    if (bytes_read != (size_t)length) {
        return -1;
    }
    model_bytes = bytes_read;
    return 0;
}

static void check_expected_output(const float output[4]) {
    CHECK(output[0] == 0.0f);
    CHECK(output[1] == 0.0f);
    CHECK(output[2] == 1.0f);
    CHECK(output[3] == 5.0f);
}

static void test_validation(void) {
    JarvisSpeechOnnxFixture fixture;
    float input[4] = {-2.0f, -1.0f, 0.0f, 2.0f};
    float output[4];
    memset(&fixture, 0, sizeof(fixture));
    CHECK(jarvis_speech_onnx_fixture_init(NULL, model_data, model_bytes) ==
          JARVIS_SPEECH_ONNX_FIXTURE_INVALID_ARGUMENT);
    CHECK(jarvis_speech_onnx_fixture_init(&fixture, NULL, model_bytes) ==
          JARVIS_SPEECH_ONNX_FIXTURE_INVALID_ARGUMENT);
    CHECK(jarvis_speech_onnx_fixture_init(&fixture, model_data, 0u) ==
          JARVIS_SPEECH_ONNX_FIXTURE_INVALID_ARGUMENT);
    CHECK(jarvis_speech_onnx_fixture_run(&fixture, input, output) ==
          JARVIS_SPEECH_ONNX_FIXTURE_INVALID_STATE);
    CHECK(jarvis_speech_onnx_fixture_run(NULL, input, output) ==
          JARVIS_SPEECH_ONNX_FIXTURE_INVALID_ARGUMENT);
    CHECK(jarvis_speech_onnx_fixture_destroy(NULL) ==
          JARVIS_SPEECH_ONNX_FIXTURE_INVALID_ARGUMENT);
    CHECK(strcmp(jarvis_speech_onnx_fixture_status_name(
                     JARVIS_SPEECH_ONNX_FIXTURE_OUTPUT_INVALID),
                 "output-invalid") == 0);
    CHECK(strcmp(jarvis_speech_onnx_fixture_status_name(99), "invalid") == 0);
}

static void test_inference_and_lifecycle(void) {
    JarvisSpeechOnnxFixture fixture;
    float input[4] = {-2.0f, -1.0f, 0.0f, 2.0f};
    float output[4];
    CHECK(jarvis_speech_onnx_fixture_init(
              &fixture, model_data, model_bytes) ==
          JARVIS_SPEECH_ONNX_FIXTURE_OK);
    CHECK(fixture.state == JARVIS_SPEECH_ONNX_FIXTURE_READY);
    CHECK(fixture.abi_version == JARVIS_SPEECH_ONNX_FIXTURE_ABI_VERSION);
    CHECK(fixture.struct_size == sizeof(fixture));
    CHECK(jarvis_speech_onnx_fixture_last_error(&fixture)[0] == '\0');
    CHECK(jarvis_speech_onnx_fixture_run(&fixture, input, output) ==
          JARVIS_SPEECH_ONNX_FIXTURE_OK);
    check_expected_output(output);
    CHECK(jarvis_speech_onnx_fixture_run(&fixture, NULL, output) ==
          JARVIS_SPEECH_ONNX_FIXTURE_INVALID_ARGUMENT);
    CHECK(jarvis_speech_onnx_fixture_run(&fixture, input, NULL) ==
          JARVIS_SPEECH_ONNX_FIXTURE_INVALID_ARGUMENT);
    CHECK(jarvis_speech_onnx_fixture_destroy(&fixture) ==
          JARVIS_SPEECH_ONNX_FIXTURE_OK);
    CHECK(fixture.state == JARVIS_SPEECH_ONNX_FIXTURE_DESTROYED);
    CHECK(jarvis_speech_onnx_fixture_destroy(&fixture) ==
          JARVIS_SPEECH_ONNX_FIXTURE_INVALID_STATE);
    CHECK(jarvis_speech_onnx_fixture_run(&fixture, input, output) ==
          JARVIS_SPEECH_ONNX_FIXTURE_INVALID_STATE);
}

static void test_repeated_lifecycles(void) {
    unsigned int iteration;
    for (iteration = 0u; iteration < REPEAT_LIFECYCLES; ++iteration) {
        JarvisSpeechOnnxFixture fixture;
        float input[4] = {-2.0f, -1.0f, 0.0f, 2.0f};
        float output[4];
        CHECK(jarvis_speech_onnx_fixture_init(
                  &fixture, model_data, model_bytes) ==
              JARVIS_SPEECH_ONNX_FIXTURE_OK);
        CHECK(jarvis_speech_onnx_fixture_run(&fixture, input, output) ==
              JARVIS_SPEECH_ONNX_FIXTURE_OK);
        check_expected_output(output);
        CHECK(jarvis_speech_onnx_fixture_destroy(&fixture) ==
              JARVIS_SPEECH_ONNX_FIXTURE_OK);
    }
}

static void test_invalid_model_is_rejected(void) {
    JarvisSpeechOnnxFixture fixture;
    unsigned char invalid_model[4] = {0u, 1u, 2u, 3u};
    CHECK(jarvis_speech_onnx_fixture_init(
              &fixture, invalid_model, sizeof(invalid_model)) ==
          JARVIS_SPEECH_ONNX_FIXTURE_RUNTIME_ERROR);
    CHECK(fixture.state == JARVIS_SPEECH_ONNX_FIXTURE_FAULTED);
    CHECK(jarvis_speech_onnx_fixture_last_error(&fixture)[0] != '\0');
    CHECK(jarvis_speech_onnx_fixture_destroy(&fixture) ==
          JARVIS_SPEECH_ONNX_FIXTURE_OK);
}

int main(int argc, char **argv) {
    if (argc != 2 || load_model(argv[1]) != 0) {
        fprintf(stderr, "usage: %s <tiny-model.onnx>\n", argv[0]);
        return 2;
    }
    test_validation();
    test_inference_and_lifecycle();
    test_repeated_lifecycles();
    test_invalid_model_is_rejected();
    if (failures != 0) {
        fprintf(stderr, "ONNX fixture contract failed: %d/%d checks\n",
                failures, checks);
        return 1;
    }
    printf("ONNX fixture contract passed: %d checks across %u lifecycles\n",
           checks, REPEAT_LIFECYCLES + 1u);
    return 0;
}
